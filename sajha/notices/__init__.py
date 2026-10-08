# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
System notices: SAJHA telling the people who run it that something needs attention.

One service every subsystem reports into (``notices.*`` in application.yml). The console
shows the result as a banner on every page, a "System status" panel on the dashboard and
a navbar badge; admin endpoints list, acknowledge and clear notices. Design and as-built
behaviour: docs/architecture/System Notices.md.

The API for sources is small and stable; call it from anywhere, it never raises::

    from sajha import notices
    notices.raise_notice('db.schema', severity='error', source='db',
                         title='Database schema is out of date',
                         detail='... what happened, what it affects, what to do ...',
                         link='/help/guides/Database%20Setup.md',
                         ttl_minutes=0)        # 0: checked once at start-up, never times out
    notices.clear_notice('db.schema')

* ``id`` is the stable identity of the condition, chosen by the source
  (``<source>.<condition>[:<subject>]``). Raising it again refreshes the same notice.
* A source clears what it raised when the condition ends; a notice not refreshed for its
  ``ttl_minutes`` (default ``notices.default_ttl_minutes``; 0 = never) clears by itself.
* ``holder``: for a condition each worker judges for itself (a circuit breaker is per
  process), pass ``holder=WORKER_ID``. The notice then clears only when no worker still
  holds it, so one worker's healthy breaker does not clear another's open one.

Notices live in the state store (``state.backend``), so every worker sees the same set;
every transition (raised, escalated, acknowledged, cleared) is an audit event; at most
``notices.max_active`` are open (the oldest, lowest-severity one goes first).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SEVERITIES = ('info', 'warning', 'error', 'critical')
RANK = {s: i for i, s in enumerate(SEVERITIES)}
AUDIENCES = ('admin', 'everyone')
STATES = ('active', 'acknowledged', 'cleared')
FORWARD_CHANNELS = ('log', 'webhook', 'email')

KEY = 'notice:'                  # notice:<id> -> the notice (one entry per id)
VERSION_KEY = 'notices:version'  # bumped on every transition; the console stream watches it

_FOREVER = 365 * 86400.0         # store expiry of an open notice that never times out


def _cfg(key: str, default: str) -> str:
    try:
        from sajha.core.config import _get
        v = _get(key, default)
        return default if v is None or v == '' else str(v)
    except Exception:
        return default


def enabled() -> bool:
    from sajha.core.config import parse_bool
    return parse_bool(_cfg('notices.enabled', 'true'), True)


def _num(key: str, default: float) -> float:
    try:
        return float(_cfg(key, str(default)))
    except (TypeError, ValueError):
        return default


def max_active() -> int:
    return max(1, int(_num('notices.max_active', 500)))


def default_ttl_seconds() -> float:
    return max(0.0, _num('notices.default_ttl_minutes', 30)) * 60


def cleared_retention_seconds() -> float:
    return max(60.0, _num('notices.cleared_retention_minutes', 1440) * 60)


def banner_min_severity() -> str:
    v = _cfg('notices.banner_min_severity', 'error').strip().lower()
    return v if v in ('error', 'critical') else 'error'


# ── forwarding to alert channels (notices.forward) ──────────────────

def _forward_rules_raw() -> List[Dict[str, Any]]:
    env = os.environ.get('SAJHA_NOTICES_FORWARD')
    if env:
        try:
            data = json.loads(env)
        except ValueError as e:
            logger.warning(f'SAJHA_NOTICES_FORWARD is not a JSON list: {e}')
            return []
    else:
        from pathlib import Path
        path = Path(os.environ.get('SAJHA_CONFIG_FILE', 'config/application.yml'))
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            import yaml
            data = ((yaml.safe_load(path.read_text(encoding='utf-8')) or {}).get('notices') or {}).get('forward')
        except Exception:
            data = None
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def parse_forward_rules(raw: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Valid rules ``{min_severity, channel}`` and the reasons the others were dropped."""
    rules, errors = [], []
    for i, r in enumerate(raw):
        sev = str(r.get('min_severity') or 'critical').lower()
        ch = r.get('channel') or {'type': 'log'}
        if isinstance(ch, str):
            ch = {'type': ch}
        ctype = str(ch.get('type') or 'log')
        try:
            if sev not in SEVERITIES:
                raise ValueError(f'min_severity must be one of {", ".join(SEVERITIES)}')
            if ctype not in FORWARD_CHANNELS:
                raise ValueError(f'channel type must be one of {", ".join(FORWARD_CHANNELS)}')
            if ctype == 'webhook':
                from sajha.observability.alerts import check_webhook_url
                check_webhook_url(str(ch.get('url') or ''))
            if ctype == 'email' and not ch.get('to'):
                raise ValueError('an email channel needs "to"')
        except ValueError as e:
            errors.append(f'notices.forward[{i}]: {e}')
            continue
        rules.append({'min_severity': sev, 'channel': dict(ch)})
    return rules, errors


# ── the service ─────────────────────────────────────────────────────

class NoticeService:
    """Notices in one state store. Module functions use the process's instance."""

    def __init__(self, store=None, forward: Optional[List[Dict[str, Any]]] = None):
        self._store = store
        self._forward = forward
        self._lock = threading.Lock()

    @property
    def store(self):
        if self._store is None:
            from sajha.core.state import get_state_store
            self._store = get_state_store()
        return self._store

    @property
    def forward_rules(self) -> List[Dict[str, Any]]:
        if self._forward is None:
            rules, errors = parse_forward_rules(_forward_rules_raw())
            for e in errors:
                logger.warning(f'{e}; rule ignored')
            self._forward = rules
        return self._forward

    # -- reading --
    def get(self, notice_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get(KEY + notice_id)

    def all(self) -> List[Dict[str, Any]]:
        return [v for _, v in self.store.scan(KEY) if isinstance(v, dict)]

    def version(self) -> int:
        try:
            return int(self.store.get(VERSION_KEY) or 0)
        except (TypeError, ValueError):
            return 0

    def list(self, state: str = 'open', source: Optional[str] = None) -> List[Dict[str, Any]]:
        """``open`` (active + acknowledged), ``cleared`` or ``all``; most severe first."""
        self.sweep()
        out = []
        for n in self.all():
            is_open = n.get('state') != 'cleared'
            if (state == 'open' and not is_open) or (state == 'cleared' and is_open):
                continue
            if source and n.get('source') != source:
                continue
            out.append(n)
        if state == 'cleared':
            out.sort(key=lambda n: -(n.get('cleared_at') or 0))
        else:
            out.sort(key=lambda n: (-RANK.get(n.get('severity'), 0), n.get('since') or 0))
        return out

    # -- writing --
    def raise_notice(self, notice_id: str, severity: str = 'warning', source: str = '', title: str = '',
                     detail: str = '', link: str = '', audience: str = 'admin',
                     ttl_minutes: Optional[float] = None, holder: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not enabled() or not notice_id:
            return None
        severity = severity if severity in SEVERITIES else 'warning'
        audience = audience if audience in AUDIENCES else 'admin'
        ttl = default_ttl_seconds() if ttl_minutes is None else max(0.0, float(ttl_minutes)) * 60
        key = KEY + notice_id
        cur = self.store.get(key)
        if cur is None or cur.get('state') == 'cleared':
            if not self._make_room(notice_id, severity):
                logger.warning(f'notice {notice_id} not kept: notices.max_active ({max_active()}) '
                               'open notices are all more severe')
                return None
        seen: Dict[str, Any] = {}

        def fn(old):
            seen.clear()
            now = time.time()
            if old is None or old.get('state') == 'cleared':
                n = {'id': notice_id, 'since': now, 'state': 'active', 'acknowledged_by': None,
                     'acknowledged_at': None, 'cleared_at': None, 'cleared_reason': None, 'holders': {}}
                seen['transition'] = 'raised'
            else:
                n = dict(old)
                if RANK[severity] > RANK.get(old.get('severity'), 0):
                    seen['transition'] = 'escalated'
                    if n.get('state') == 'acknowledged':     # worse than what was acknowledged: shout again
                        n.update(state='active', acknowledged_by=None, acknowledged_at=None)
                elif severity != old.get('severity'):
                    seen['transition'] = 'changed'
                elif (title, detail, link, audience) != (old.get('title'), old.get('detail'),
                                                         old.get('link'), old.get('audience')):
                    seen['transition'] = 'updated'
            holders = {w: t for w, t in (n.get('holders') or {}).items() if not ttl or now - t <= ttl}
            if holder:
                holders[holder] = now
            n.update(severity=severity, source=source or n.get('source') or '', title=title or notice_id,
                     detail=detail, link=link, audience=audience, last_seen=now, ttl=ttl, holders=holders)
            return n

        n = self.store.update(key, fn, ttl=(ttl * 2 + 3600) if ttl else _FOREVER)
        tr = seen.get('transition')
        if tr:
            self._changed(n, tr, by=None)
        return n

    def clear(self, notice_id: str, holder: Optional[str] = None, reason: str = 'source',
              by: Optional[str] = None) -> bool:
        """Clear (``holder``: only this worker stops holding it). True when the notice cleared."""
        key = KEY + notice_id
        cur = self.store.get(key)
        if cur is None or cur.get('state') == 'cleared':
            return False
        seen: Dict[str, Any] = {}

        def others(old, now):
            ttl = float(old.get('ttl') or 0)
            return {w: t for w, t in (old.get('holders') or {}).items()
                    if w != holder and (not ttl or now - t <= ttl)}

        def fn(old):
            seen.clear()
            if old is None or old.get('state') == 'cleared':
                return old
            n = dict(old)
            if holder:
                n['holders'] = others(old, time.time())
                if n['holders']:
                    return n            # another worker still holds the condition
            n.update(state='cleared', cleared_at=time.time(), cleared_reason=reason, holders={})
            seen['transition'] = 'cleared'
            return n

        open_ttl = float(cur.get('ttl') or 0)
        stays = bool(holder) and bool(others(cur, time.time()))
        n = self.store.update(key, fn, ttl=((open_ttl * 2 + 3600) if open_ttl else _FOREVER) if stays
                              else cleared_retention_seconds())
        if seen.get('transition'):
            self._changed(n, 'cleared', by=by, reason=reason)
            return True
        return False

    def acknowledge(self, notice_id: str, by: str) -> Optional[Dict[str, Any]]:
        """Acknowledge an active notice; returns it (unchanged when not active), None when unknown."""
        key = KEY + notice_id
        cur = self.store.get(key)
        if cur is None:
            return None
        if cur.get('state') != 'active':
            return cur
        seen: Dict[str, Any] = {}

        def fn(old):
            seen.clear()
            if old is None or old.get('state') != 'active':
                return old
            n = dict(old)
            n.update(state='acknowledged', acknowledged_by=by, acknowledged_at=time.time())
            seen['transition'] = 'acknowledged'
            return n

        ttl = float(cur.get('ttl') or 0)
        n = self.store.update(key, fn, ttl=(ttl * 2 + 3600) if ttl else _FOREVER)
        if seen.get('transition'):
            self._changed(n, 'acknowledged', by=by)
        return n

    def sweep(self, now: Optional[float] = None) -> int:
        """Clear open notices not refreshed for their ttl.  Returns how many cleared."""
        now = now or time.time()
        n = 0
        for x in self.all():
            ttl = float(x.get('ttl') or 0)
            if x.get('state') != 'cleared' and ttl and now - float(x.get('last_seen') or 0) > ttl:
                n += bool(self.clear(x['id'], reason='ttl'))
        return n

    def _make_room(self, new_id: str, severity: str) -> bool:
        """Keep at most notices.max_active open: evict the lowest-severity, oldest one (maybe the new one)."""
        opened = [x for x in self.all() if x.get('state') != 'cleared' and x.get('id') != new_id]
        cap = max_active()
        while len(opened) >= cap:
            victim = min(opened, key=lambda x: (RANK.get(x.get('severity'), 0), x.get('since') or 0))
            if RANK.get(victim.get('severity'), 0) > RANK[severity]:
                return False
            self.clear(victim['id'], reason='evicted')
            opened.remove(victim)
        return True

    # -- side effects of a transition --
    def _changed(self, n: Dict[str, Any], transition: str, by: Optional[str], reason: Optional[str] = None) -> None:
        try:
            self.store.incr(VERSION_KEY, 1)
        except Exception as e:
            logger.debug(f'notices version bump failed: {e}')
        try:
            from sajha.core.audit import get_audit_logger
            get_audit_logger().log(f'notice.{transition}', user_id=by or 'system', resource_type='notice',
                                   resource_id=n.get('id'), details=json.dumps(
                                       {'severity': n.get('severity'), 'source': n.get('source'),
                                        'title': n.get('title'), 'audience': n.get('audience'),
                                        **({'reason': reason} if reason else {})}, default=str))
        except Exception as e:
            logger.debug(f'notice audit failed: {e}')
        log = logger.warning if transition in ('raised', 'escalated') and RANK.get(n.get('severity'), 0) >= 1 \
            else logger.info
        log(f'Notice {transition}: [{n.get("severity")}] {n.get("id")}: {n.get("title")}')
        if transition in ('raised', 'escalated'):
            self._forward_notice(n, transition)

    def _forward_notice(self, n: Dict[str, Any], transition: str) -> None:
        rules = [r for r in self.forward_rules if RANK.get(n.get('severity'), 0) >= RANK[r['min_severity']]]
        if not rules:
            return
        from sajha.observability import alerts
        payload = {'type': 'sajha.notice', 'transition': transition, 'source': 'sajha',
                   'notice': public(n, admin=True),
                   'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        text = f'NOTICE [{n.get("severity")}] {n.get("title")} ({n.get("id")})'
        for r in rules:
            ch = r['channel']
            ctype = ch.get('type') or 'log'
            try:
                if ctype == 'webhook':
                    threading.Thread(target=alerts.send_webhook, args=(str(ch.get('url')), payload),
                                     name='sajha-notice-webhook', daemon=True).start()
                elif ctype == 'email':
                    threading.Thread(target=alerts.send_email, args=(ch, text, payload),
                                     name='sajha-notice-email', daemon=True).start()
                else:
                    logging.getLogger('sajha.observability.alerts').warning(text)
            except Exception as e:
                logger.error(f'notice forward ({ctype}) failed to start: {e}')


# ── what a viewer sees ──────────────────────────────────────────────

def public(n: Dict[str, Any], admin: bool) -> Dict[str, Any]:
    out = {k: n.get(k) for k in ('id', 'severity', 'source', 'title', 'detail', 'link', 'since', 'last_seen',
                                 'audience', 'state', 'acknowledged_by', 'acknowledged_at', 'cleared_at',
                                 'cleared_reason')}
    if admin:
        out['ttl_minutes'] = round(float(n.get('ttl') or 0) / 60, 2)
        out['workers'] = len(n.get('holders') or {})
    return out


def visible(n: Dict[str, Any], is_admin: bool) -> bool:
    return bool(is_admin) or n.get('audience') == 'everyone'


def shouts(n: Dict[str, Any]) -> bool:
    """Counts on the badge and may take the banner: unacknowledged, or critical (never hidden)."""
    return n.get('state') == 'active' or (n.get('severity') == 'critical' and n.get('state') != 'cleared')


def view(is_admin: bool, authenticated: bool = True, include_cleared: bool = False,
         service: Optional[NoticeService] = None) -> Dict[str, Any]:
    """The banner, badge and panel content for one viewer."""
    out: Dict[str, Any] = {'enabled': enabled(), 'notices': [], 'banner': None, 'others': 0, 'badge': 0,
                           'is_admin': bool(is_admin)}
    if not authenticated or not out['enabled']:
        return out
    svc = service or get_service()
    try:
        opened = [n for n in svc.list('open') if visible(n, is_admin)]
    except Exception as e:
        logger.debug(f'notices view failed: {e}')
        return out
    floor = RANK[banner_min_severity()]
    loud = [n for n in opened if shouts(n) and RANK.get(n.get('severity'), 0) >= RANK['warning']]
    banner = next((n for n in loud if RANK.get(n.get('severity'), 0) >= floor), None)
    out['notices'] = [public(n, is_admin) for n in opened]
    out['badge'] = len(loud)
    if banner is not None:
        out['banner'] = public(banner, is_admin)
        out['others'] = len(opened) - 1
    if include_cleared:
        out['cleared'] = [public(n, is_admin) for n in svc.list('cleared') if visible(n, is_admin)][:50]
    out['version'] = svc.version()
    return out


def template_view(request) -> Dict[str, Any]:
    """For base.html: the signed-in viewer's view, from the auth the route resolved (else empty)."""
    auth = getattr(getattr(request, 'state', None), 'auth', None)
    if auth is None or not getattr(auth, 'authenticated', False):
        return {'enabled': enabled(), 'notices': [], 'banner': None, 'others': 0, 'badge': 0, 'is_admin': False}
    return view(bool(auth.is_admin))


# ── module API (stable: other subsystems call these) ───────────────

_service: Optional[NoticeService] = None
_service_lock = threading.Lock()


def get_service() -> NoticeService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = NoticeService()
    return _service


def set_service(svc: Optional[NoticeService]) -> None:
    """Install a service (tests); None rebuilds from the state store on next use."""
    global _service
    with _service_lock:
        _service = svc


def raise_notice(notice_id: str, severity: str = 'warning', source: str = '', title: str = '', detail: str = '',
                 link: str = '', audience: str = 'admin', ttl_minutes: Optional[float] = None,
                 holder: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Raise or refresh a notice. Never raises; returns the notice or None."""
    try:
        return get_service().raise_notice(notice_id, severity=severity, source=source, title=title, detail=detail,
                                          link=link, audience=audience, ttl_minutes=ttl_minutes, holder=holder)
    except Exception as e:
        logger.warning(f'raise_notice({notice_id}) failed: {e}')
        return None


def clear_notice(notice_id: str, holder: Optional[str] = None, reason: str = 'source') -> bool:
    """The source's condition ended. Never raises; True when the notice cleared."""
    try:
        return get_service().clear(notice_id, holder=holder, reason=reason)
    except Exception as e:
        logger.warning(f'clear_notice({notice_id}) failed: {e}')
        return False


def acknowledge_notice(notice_id: str, by: str) -> Optional[Dict[str, Any]]:
    return get_service().acknowledge(notice_id, by)


def list_notices(state: str = 'open', source: Optional[str] = None) -> List[Dict[str, Any]]:
    return get_service().list(state, source)


__all__ = ['raise_notice', 'clear_notice', 'acknowledge_notice', 'list_notices', 'view', 'get_service',
           'set_service', 'NoticeService', 'SEVERITIES', 'AUDIENCES']
