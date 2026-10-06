"""
SAJHA MCP Server — human approval of tool calls (``effect: require_approval``).

Pending approvals, decisions and grants live in the state store, so every worker sees
them (``state.backend: redis`` or ``database``; ``memory`` is one process):

* ``policy:approval:<id>``            the approval record (tool, arguments, caller, rule, status ...)
* ``policy:approval-pending:<who>:<fp>`` the id of the pending approval for this caller and call,
  so repeating a call while it waits returns the same id
* ``policy:approval-grant:<who>:<fp>``  set on approve; :func:`consume_grant` pops it
  atomically, so an approval runs the call once, on one worker

``<fp>`` is the call's fingerprint (tool + canonical arguments, sha256). A new approval is
announced to ``policy.approvals.notify_url`` through the alert webhook's SSRF guard.
Design: docs/architecture/Policy and Audit.md, section 5.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PREFIX = 'policy:approval:'
PENDING = 'policy:approval-pending:'
GRANT = 'policy:approval-grant:'
STATUSES = ('pending', 'approved', 'denied', 'used', 'expired')


class ApprovalError(ValueError):
    """An approval that cannot be decided (unknown, already decided, self-approval)."""


def _cfg_int(key: str, default: int) -> int:
    from sajha.core.config import _get
    try:
        return int(float(_get(key, '') or default))
    except (TypeError, ValueError):
        return default


def _cfg_bool(key: str, default: bool) -> bool:
    from sajha.core.config import _bool
    return _bool(key, default)


def ttl_seconds() -> int:
    return max(60, _cfg_int('policy.approvals.ttl_seconds', 86400))


def grant_ttl_seconds() -> int:
    return max(10, _cfg_int('policy.approvals.grant_ttl_seconds', 3600))


def _store():
    from sajha.core.state import get_state_store
    return get_state_store()


def fingerprint(tool: str, arguments: Any) -> str:
    canonical = json.dumps({'tool': tool, 'arguments': arguments}, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def who(caller) -> str:
    """The identity an approval is bound to: the user and, when present, the API key."""
    user = getattr(caller, 'user_id', '') or 'anonymous'
    key = getattr(caller, 'api_key', '') or ''
    return hashlib.sha256(f'{user}|{key}'.encode()).hexdigest()[:32]


def request(*, tool: str, arguments: Dict[str, Any], caller, source: str, rule: str, reason: str,
            ttl: Optional[float] = None) -> Dict[str, Any]:
    """The pending approval for this caller and call: the existing one, or a new one."""
    st = _store()
    fp = fingerprint(tool, arguments)
    pkey = PENDING + who(caller) + ':' + fp
    ttl = int(ttl or ttl_seconds())
    existing = st.get(pkey)
    if existing:
        rec = st.get(PREFIX + existing)
        if rec and rec.get('status') == 'pending':
            return rec
        st.delete(pkey)
    aid = uuid.uuid4().hex[:16]
    now = time.time()
    rec = {'id': aid, 'status': 'pending', 'tool': tool, 'arguments': arguments, 'fingerprint': fp,
           'caller': {'user_id': getattr(caller, 'user_id', '') or 'anonymous',
                      'api_key': getattr(caller, 'api_key', '') or '',
                      'roles': list(getattr(caller, 'roles', ()) or ()),
                      'auth_type': getattr(caller, 'auth_type', '') or ''},
           'who': who(caller), 'source': source, 'rule': rule, 'reason': reason,
           'created_at': now, 'expires_at': now + ttl, 'decided_by': None, 'decided_at': None, 'note': ''}
    if not st.add(pkey, aid, ttl=ttl):            # another worker created it a moment ago
        other = st.get(pkey)
        rec_other = st.get(PREFIX + other) if other else None
        if rec_other:
            return rec_other
        st.set(pkey, aid, ttl=ttl)
    # the record outlives its pending window so the page can show the decision
    st.set(PREFIX + aid, rec, ttl=ttl + 7 * 86400)
    _audit('policy.approval_required', rec)
    _notify(rec)
    return rec


def get(aid: str) -> Optional[Dict[str, Any]]:
    rec = _store().get(PREFIX + str(aid))
    return _expire(rec) if rec else None


def _expire(rec: Dict[str, Any]) -> Dict[str, Any]:
    if rec.get('status') == 'pending' and rec.get('expires_at', 0) < time.time():
        rec = dict(rec, status='expired')
    return rec


def list_all(status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    out = [_expire(v) for _k, v in _store().scan(PREFIX) if isinstance(v, dict) and v.get('id')]
    if status:
        out = [r for r in out if r.get('status') == status]
    out.sort(key=lambda r: r.get('created_at', 0), reverse=True)
    return out[:limit]


def decide(aid: str, approve: bool, by_user: str, note: str = '') -> Dict[str, Any]:
    """Approve or deny a pending approval. Raises :class:`ApprovalError`."""
    st = _store()
    key = PREFIX + str(aid)
    allow_self = _cfg_bool('policy.approvals.allow_self_approval', False)

    def fn(cur):
        if not cur:
            raise ApprovalError('no such approval')
        cur = _expire(cur)
        if cur.get('status') != 'pending':
            raise ApprovalError(f"this approval is already {cur.get('status')}")
        if not allow_self and (cur.get('caller') or {}).get('user_id') == by_user:
            raise ApprovalError('you cannot decide an approval for your own call '
                                '(policy.approvals.allow_self_approval)')
        return dict(cur, status='approved' if approve else 'denied', decided_by=by_user,
                    decided_at=time.time(), note=str(note or '')[:500])

    rec = st.update(key, fn)
    st.delete(PENDING + rec['who'] + ':' + rec['fingerprint'])
    if approve:
        st.set(GRANT + rec['who'] + ':' + rec['fingerprint'], rec['id'], ttl=grant_ttl_seconds())
    _audit('approval.approve' if approve else 'approval.deny', rec, actor=by_user)
    return rec


def consume_grant(tool: str, arguments: Dict[str, Any], caller) -> Optional[Dict[str, Any]]:
    """The approved approval for this exact call, marked used; None when there is none."""
    st = _store()
    fp = fingerprint(tool, arguments)
    aid = st.pop(GRANT + who(caller) + ':' + fp)
    if not aid:
        return None

    def fn(cur):
        if not cur or cur.get('status') != 'approved':
            raise ApprovalError('grant without an approved record')
        return dict(cur, status='used', used_at=time.time())

    try:
        return st.update(PREFIX + aid, fn)
    except ApprovalError:
        return None


def _audit(event: str, rec: Dict[str, Any], actor: Optional[str] = None) -> None:
    try:
        from sajha import audit
        c = rec.get('caller') or {}
        audit.record(event, actor={'user': actor or c.get('user_id'), 'api_key': '' if actor else c.get('api_key'),
                                   'roles': [] if actor else c.get('roles', [])},
                     resource={'type': 'tool', 'id': rec.get('tool')},
                     outcome=rec.get('status'),
                     details={'approval_id': rec.get('id'), 'rule': rec.get('rule'), 'source': rec.get('source'),
                              'requested_by': c.get('user_id'), 'fingerprint': rec.get('fingerprint'),
                              'argument_names': sorted((rec.get('arguments') or {}).keys()),
                              'note': rec.get('note') or None})
    except Exception as e:
        logger.debug(f'approval audit: {e}')


def _notify(rec: Dict[str, Any]) -> None:
    from sajha.core.config import _get
    url = (_get('policy.approvals.notify_url', '') or '').strip()
    if not url:
        return
    fmt = (_get('policy.approvals.notify_format', 'generic') or 'generic').strip().lower()
    c = rec.get('caller') or {}
    text = (f"SAJHA approval needed: {c.get('user_id')} wants to run {rec.get('tool')} "
            f"(rule {rec.get('rule')}): {rec.get('reason')}. Approve or deny on /admin/approvals "
            f"(id {rec.get('id')}).")
    payload = {'text': text} if fmt == 'slack' else {
        'event': 'policy.approval_required', 'id': rec.get('id'), 'tool': rec.get('tool'),
        'user': c.get('user_id'), 'rule': rec.get('rule'), 'reason': rec.get('reason'),
        'source': rec.get('source'), 'created_at': rec.get('created_at'), 'text': text}

    def send():
        try:
            from sajha.observability.alerts import send_webhook
            send_webhook(url, payload)
        except Exception as e:
            logger.warning(f'approval notification failed: {e}')

    threading.Thread(target=send, name='sajha-approval-notify', daemon=True).start()
