"""
SAJHA Net changes: every administrative change to a net goes through :func:`perform`, which applies it,
keeps it in the net's change history with who, when, the reason and how to undo it, and audits it
(design §17: reasons on every action, blast radius before a destructive one, undo from the history).

* :func:`perform`: one change (``block_add``, ``block_remove``, ``link``, ``unlink``, ``role_map``,
  ``name_matching``, ``trust``, ``approve``, ``unapprove``, ``pin_add``, ``pin_remove``, ``seed_remove``,
  ``sponsor_add``, ``sponsor_remove``, and the changes that cannot be undone: ``revoke``, ``forget_key``,
  ``ca_token``, ``renew``, ``resync``). It calls the same service methods as the admin API, so their
  checks hold (a caller that arrived through the net is refused; a block needs a reason).
* :func:`history`: the newest changes of a net (optionally those naming one instance).
* :func:`undo`: apply a change's inverse as a new change (itself undoable), with a reason.
* :func:`blast_radius`: what a change would take away, in numbers and one sentence, before it is made.

The history is ``<sajhanet.data_dir>/<net>/changes.json`` in the storage backend (the newest
:data:`KEEP`), so every worker sees it. Each change and each undo is also an audit record
(``sajhanet.change_recorded``, ``sajhanet.change_undone``), next to the record the change itself writes.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import fnmatch
import secrets
import time
from typing import Any, Dict, List, Optional

#: Changes kept per net (the oldest are dropped).
KEEP = 500

#: Changes that have an inverse.
UNDOABLE = ('block_add', 'block_remove', 'link', 'unlink', 'role_map', 'name_matching', 'trust', 'approve',
            'unapprove', 'pin_add', 'pin_remove', 'seed_remove', 'sponsor_add', 'sponsor_remove')
#: Changes recorded with their reason but never undone, and why.
FINAL = {'revoke': 'a revoked certificate stays revoked; enroll the instance under a new name',
         'forget_key': 'the forgotten key is not kept; the instance is admitted again on its next contact',
         'ca_token': 'a token is single use and expires by itself',
         'renew': 'the old certificate is replaced',
         'resync': 'a re-sync only pulls records again'}
KINDS = UNDOABLE + tuple(FINAL)


def _service():
    from sajha.net.integration import get_service
    svc = get_service()
    return svc if svc is not None and svc.shared.enabled else None


def _err(status: int, msg: str):
    from sajha.net.integration import ServiceError
    return ServiceError(status, msg)


def _now() -> str:
    from sajha.net import crypto
    return crypto.rfc3339(time.time())


def _s(p: Dict[str, Any], k: str) -> str:
    return str(p.get(k) or '').strip()


# ── the history document ────────────────────────────────────────────

def history(net: str, instance: Optional[str] = None, limit: int = 100, svc=None) -> List[Dict[str, Any]]:
    """The newest changes of ``net`` first; with ``instance``, those whose target is that instance."""
    svc = svc or _service()
    if svc is None:
        return []
    items = list(reversed(svc._list_doc(net, 'changes')))
    if instance:
        items = [c for c in items if c.get('target') == instance or c.get('target') == '*'
                 or str(c.get('target') or '').endswith('@' + instance)]
    return items[:max(1, int(limit))]


def _append(svc, net: str, entry: Dict[str, Any]) -> None:
    svc._update_list_doc(net, 'changes', lambda items: (items + [entry])[-KEEP:])


def _mark_undone(svc, net: str, cid: str, by: str, reason: str, new_id: str) -> bool:
    def fn(items):
        for c in items:
            if c.get('id') == cid and not c.get('undone_at'):
                c.update(undone_at=_now(), undone_by=by, undo_reason=reason, undone_as=new_id)
                return items
        return None
    return svc._update_list_doc(net, 'changes', fn)


# ── applying one change ─────────────────────────────────────────────

def _authz(svc):
    a = getattr(svc, 'authz', None)
    if a is None:
        raise _err(503, 'SAJHA Net identity and authorization are not running')
    return a


def _catalogs(svc):
    c = getattr(svc, 'catalogs', None)
    if c is None:
        raise _err(503, 'SAJHA Net catalogs are not running')
    return c


def _sponsorships(svc):
    from sajha.net.integration.sponsored import get_sponsorships
    return get_sponsorships(svc)


def _block_fields(b: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: b.get(k) for k in ('level', 'target_instance', 'tool', 'user', 'direction') if b.get(k)}
    out['block_reason'] = b.get('reason') or ''
    if b.get('withhold_reason'):
        out['withhold_reason'] = True
    if b.get('expires_at'):
        from sajha.net import crypto
        try:
            left = (crypto.parse_rfc3339(b['expires_at']) - time.time()) / 60.0
            out['expires_in_minutes'] = max(1, int(left + 0.999))
        except Exception:
            pass
    return out


def _apply(svc, net: str, kind: str, p: Dict[str, Any], by: str, reason: str,
           by_auth_type: Optional[str]) -> Dict[str, Any]:
    """Apply one change; ``{'result', 'target', 'summary', 'inverse'}`` (``inverse`` None: final)."""
    if kind == 'block_add':
        a = _authz(svc)
        r = a.add_block(net, _s(p, 'level'), _s(p, 'target_instance'), str(p.get('block_reason') or reason or ''), by,
                        tool=_s(p, 'tool'), user=_s(p, 'user'), direction=_s(p, 'direction') or 'inbound',
                        expires_in_minutes=p.get('expires_in_minutes'), withhold_reason=bool(p.get('withhold_reason')),
                        by_auth_type=by_auth_type)
        what = r['level'] + (' ' + r['tool'] if r.get('tool') else '') + (' ' + r['user'] if r.get('user') else '')
        return {'result': r, 'target': r.get('user') or r['target_instance'],
                'summary': f'block ({what}) on {r["target_instance"]}', 'inverse': ('block_remove', {'block_id': r['id']})}
    if kind == 'block_remove':
        a = _authz(svc)
        bid = _s(p, 'block_id')
        st = a._state(net)
        b = next((x for x in st.blocks() if x.get('id') == bid), None)
        ok = a.remove_block(net, bid, by, reason, by_auth_type)
        if not ok or b is None:
            return {'result': False, 'target': '', 'summary': '', 'inverse': None, 'missing': True}
        return {'result': True, 'target': b.get('user') or b.get('target_instance') or '',
                'summary': f'remove block ({b.get("level")}) on {b.get("target_instance")}',
                'inverse': ('block_add', _block_fields(b))}
    if kind in ('link', 'unlink'):
        a = _authz(svc)
        ru = _s(p, 'remote_user')
        before = ((a._state(net).users_doc().get('links') or {}).get(ru) or {}).get('local')
        if kind == 'link':
            r = a.link_user(net, ru, _s(p, 'local_user'), by, by_auth_type=by_auth_type)
            inv = ('link', {'remote_user': ru, 'local_user': before}) if before else ('unlink', {'remote_user': ru})
            return {'result': r, 'target': ru, 'summary': f'link {ru} to {r["local_user"]}', 'inverse': inv}
        ok = a.unlink_user(net, ru, by, by_auth_type)
        if not ok:
            return {'result': False, 'target': ru, 'summary': '', 'inverse': None, 'missing': True}
        return {'result': True, 'target': ru, 'summary': f'unlink {ru} (was {before})',
                'inverse': ('link', {'remote_user': ru, 'local_user': before})}
    if kind == 'role_map':
        a = _authz(svc)
        inst = _s(p, 'instance')
        before = dict((a._state(net).users_doc().get('role_maps') or {}).get(inst) or {})
        mp = p.get('map') if isinstance(p.get('map'), dict) else {}
        r = a.set_role_map(net, inst, mp, by, by_auth_type=by_auth_type)
        return {'result': r, 'target': inst, 'summary': f'role map for {inst}: {r["map"] or "removed"}',
                'inverse': ('role_map', {'instance': inst, 'map': before})}
    if kind == 'name_matching':
        a = _authz(svc)
        inst = _s(p, 'instance')
        was_on = inst not in set(a._state(net).users_doc().get('no_name_match') or [])
        on = bool(p.get('on', True))
        r = a.set_name_matching(net, inst, on, by, by_auth_type=by_auth_type)
        return {'result': r, 'target': inst, 'summary': f'name matching {"on" if on else "off"} for {inst}',
                'inverse': ('name_matching', {'instance': inst, 'on': was_on})}
    if kind == 'trust':
        c = _catalogs(svc)
        peer = _s(p, 'peer')
        level, pinned = c.trust_of(net, peer)
        r = c.set_trust(net, peer, _s(p, 'trust'), p.get('pinned') if isinstance(p.get('pinned'), list) else None, by)
        return {'result': r, 'target': peer, 'summary': f'trust of {peer}: {level} -> {r["trust"]}',
                'inverse': ('trust', {'peer': peer, 'trust': level, 'pinned': pinned})}
    if kind in ('approve', 'unapprove'):
        c = _catalogs(svc)
        peer, tool = _s(p, 'peer'), _s(p, 'tool')
        r = c.approve(net, peer, tool, kind == 'approve', by)
        return {'result': r, 'target': peer, 'summary': f'{"approve" if kind == "approve" else "withdraw approval of"} '
                                                        f'{tool} from {peer}',
                'inverse': ('unapprove' if kind == 'approve' else 'approve', {'peer': peer, 'tool': tool})}
    if kind == 'pin_add':
        tp = _s(p, 'thumbprint')
        had = tp in svc.runtime_pins(net)
        r = svc.add_pin(net, tp, by)
        return {'result': r, 'target': '', 'summary': f'pin {tp[:12]}…',
                'inverse': None if had else ('pin_remove', {'thumbprint': tp})}
    if kind == 'pin_remove':
        tp = _s(p, 'thumbprint')
        ok = svc.remove_pin(net, tp, by)
        if not ok:
            return {'result': False, 'target': '', 'summary': '', 'inverse': None, 'missing': True}
        return {'result': True, 'target': '', 'summary': f'unpin {tp[:12]}…', 'inverse': ('pin_add', {'thumbprint': tp})}
    if kind == 'seed_remove':
        url = _s(p, 'url').rstrip('/')
        seed = next((s for s in svc.runtime_seeds(net) if s.get('url') == url), None)
        ok = svc.remove_runtime_seed(net, url, by)
        if not ok or seed is None:
            return {'result': False, 'target': '', 'summary': '', 'inverse': None, 'missing': True}
        return {'result': True, 'target': seed.get('name') or '', 'summary': f'remove runtime seed {url}',
                'inverse': ('seed_restore', {'seed': seed})}
    if kind == 'seed_restore':                                    # the inverse of seed_remove only
        seed = p.get('seed') if isinstance(p.get('seed'), dict) else {}
        url = str(seed.get('url') or '')
        if not url:
            raise _err(400, 'no seed to restore')
        svc._update_list_doc(net, 'runtime_seeds',
                             lambda items: [s for s in items if s.get('url') != url] + [dict(seed)])
        from sajha.net.integration import _audit
        _audit('runtime_seed_restored', by, {'net': net, 'url': url})
        return {'result': {'net': net, 'url': url}, 'target': seed.get('name') or '',
                'summary': f'restore runtime seed {url}', 'inverse': ('seed_remove', {'url': url})}
    if kind == 'sponsor_add':
        sp = _sponsorships(svc)
        data = dict(p)
        data['net'] = net
        r = sp.add(data, by)
        inst = str(r.get('instance_name') or data.get('instance_name') or '')
        return {'result': r, 'target': inst, 'summary': f'sponsor {data.get("upstream")} as {inst}',
                'inverse': ('sponsor_remove', {'instance': inst})}
    if kind == 'sponsor_remove':
        sp = _sponsorships(svc)
        inst = _s(p, 'instance')
        read, _w = sp._doc()
        spec = next((x for x in (read() or {}).get('items') or []
                     if str(x.get('net')) == net and str(x.get('instance_name')) == inst), None)
        ok = sp.remove(net, inst, by)
        if not ok:
            return {'result': False, 'target': inst, 'summary': '', 'inverse': None, 'missing': True}
        return {'result': True, 'target': inst, 'summary': f'stop sponsoring {inst}',
                'inverse': ('sponsor_add', {k: v for k, v in (spec or {}).items() if k != 'net'}) if spec else None}
    if kind == 'revoke':
        r = svc.ca_revoke(net, _s(p, 'instance'), _s(p, 'serial'), reason, by)
        return {'result': r, 'target': _s(p, 'instance'), 'summary':
                f'revoke {_s(p, "instance") or "certificate " + _s(p, "serial")}', 'inverse': None}
    if kind == 'forget_key':
        inst = _s(p, 'instance')
        ok = svc.forget_peer_key(net, inst, by=by)
        if not ok:
            return {'result': False, 'target': inst, 'summary': '', 'inverse': None, 'missing': True}
        return {'result': {'net': net, 'forgotten': inst}, 'target': inst, 'summary': f'forget the key of {inst}',
                'inverse': None}
    if kind == 'ca_token':
        r = svc.ca_token(net, _s(p, 'instance'), _s(p, 'host'), by)
        return {'result': r, 'target': _s(p, 'instance'), 'summary': f'enrollment token for {_s(p, "instance")}',
                'inverse': None, 'secret': True}
    if kind == 'renew':
        r = svc.renew(net, by)
        return {'result': r, 'target': '', 'summary': 'renew this server\'s certificate', 'inverse': None}
    if kind == 'resync':
        r = _authz(svc).resync(net, by)
        return {'result': r, 'target': '', 'summary': 'key directory re-sync', 'inverse': None}
    raise _err(400, f'unknown change {kind!r}; one of {", ".join(KINDS)}')


def perform(net: str, kind: str, params: Optional[Dict[str, Any]] = None, by: str = '', reason: str = '',
            by_auth_type: Optional[str] = None, undo_of: str = '', svc=None) -> Any:
    """Make one change, record it in the net's history and audit it. Returns what the underlying
    service method returns (a bool for removals: False when there was nothing to remove)."""
    from sajha.net.integration import _audit
    from sajha.net.integration.authz import NetAuthz
    svc = svc or _service()
    if svc is None:
        raise _err(503, 'SAJHA Net is off (sajhanet.enabled: false)')
    NetAuthz._local_only(by_auth_type)                  # net settings change only at this server's console
    if net not in svc.runtimes and kind != 'sponsor_add':          # sponsoring validates its entry first
        raise _err(404, f'this server is not configured for net {net!r}')
    params = dict(params or {})
    reason = (reason or '').strip()[:500]
    out = _apply(svc, net, kind, params, by, reason, by_auth_type)
    if out.get('missing'):
        return False
    inverse = out.get('inverse')
    entry = {'id': secrets.token_hex(6), 'at': _now(), 'by': by or 'admin', 'net': net, 'kind': kind,
             'target': out.get('target') or '', 'summary': out.get('summary') or kind, 'reason': reason,
             'params': {} if out.get('secret') else params,
             'undo': {'kind': inverse[0], 'params': inverse[1]} if inverse else None,
             'final': FINAL.get(kind) if inverse is None else None}
    if undo_of:
        entry['undo_of'] = undo_of
    _append(svc, net, entry)
    _audit('change_recorded', by, {'net': net, 'id': entry['id'], 'kind': kind, 'target': entry['target'],
                                   'summary': entry['summary'], 'reason': reason, 'undo_of': undo_of or None})
    return out['result']


def undo(net: str, change_id: str, by: str = '', reason: str = '', by_auth_type: Optional[str] = None,
         svc=None) -> Dict[str, Any]:
    """Apply the inverse of change ``change_id`` (a new change, recorded and undoable in its turn)."""
    from sajha.net.integration import _audit
    svc = svc or _service()
    if svc is None:
        raise _err(503, 'SAJHA Net is off (sajhanet.enabled: false)')
    reason = (reason or '').strip()
    if not reason:
        raise _err(400, 'give a reason for the undo')
    c = next((x for x in svc._list_doc(net, 'changes') if x.get('id') == change_id), None) \
        if net in svc.runtimes else None
    if c is None:
        raise _err(404, f'no change {change_id} in {net}')
    if c.get('undone_at'):
        raise _err(409, f'change {change_id} was already undone ({c.get("undone_at")}, by {c.get("undone_by")})')
    if not c.get('undo'):
        raise _err(409, f'this change cannot be undone: {c.get("final") or "it has no inverse"}')
    inv = c['undo']
    r = perform(net, inv['kind'], inv.get('params') or {}, by, reason, by_auth_type, undo_of=change_id, svc=svc)
    if r is False:
        raise _err(409, 'nothing to undo: what the change made is already gone')
    new = history(net, limit=1, svc=svc)
    new_id = new[0]['id'] if new else ''
    _mark_undone(svc, net, change_id, by or 'admin', reason, new_id)
    _audit('change_undone', by, {'net': net, 'id': change_id, 'as': new_id, 'kind': c.get('kind'),
                                 'reason': reason})
    return {'net': net, 'undone': change_id, 'as': new_id, 'result': r}


# ── blast radius ────────────────────────────────────────────────────

def _members(svc, net: str) -> List[str]:
    rt = svc.runtimes.get(net)
    node = rt.node if rt is not None else None
    try:
        return [m['name'] for m in node.members()] if node is not None else []
    except Exception:
        return []


def _remote_users(svc, net: str, home: Optional[str]) -> List[str]:
    a = getattr(svc, 'authz', None)
    st = a.nets.get(net) if a is not None else None
    if st is None:
        return []
    try:
        seen = [v for _k, v in st.node.kv.scan('seen:')]
    except Exception:
        seen = []
    return sorted({str(v.get('user')) for v in seen if home in (None, '*') or v.get('home') == home})


def _remote_tools(svc, net: str, host: Optional[str], pattern: str = '') -> List[str]:
    c = getattr(svc, 'catalogs', None)
    if c is None or c.router is None:
        return []
    try:
        rows = c.router.rows()
    except Exception:
        return []
    return sorted({r['qualified_name'] for r in rows if r['net'] == net and r['state'] in ('active', 'unavailable')
                   and (host in (None, '*') or r['host_instance'] == host)
                   and (not pattern or fnmatch.fnmatchcase(r['qualified_name'], pattern))})


def _exported_to(svc, net: str, peer: Optional[str]) -> List[str]:
    c = getattr(svc, 'catalogs', None)
    book = c.books.get(net) if c is not None else None
    if book is None:
        return []
    try:
        return sorted(t['name'] for t in book.exports(None if peer in (None, '*') else peer))
    except Exception:
        return []


def _local_callers(records: List[Dict[str, Any]], net: str, host: Optional[str]) -> List[str]:
    """Local users who called ``host``'s tools recently (``net.call_attempt`` records at this home)."""
    out = set()
    for rec in records:
        d = rec.get('details') if isinstance(rec.get('details'), dict) else {}
        if rec.get('event') != 'net.call_attempt' or (d.get('net') and d.get('net') != net):
            continue
        if host in (None, '*') or d.get('host') == host:
            u = d.get('user') or (rec.get('actor') or {}).get('user')
            if u:
                out.add(str(u))
    return sorted(out)


def blast_radius(net: str, kind: str, params: Optional[Dict[str, Any]] = None,
                 records: Optional[List[Dict[str, Any]]] = None, svc=None) -> Dict[str, Any]:
    """``{remote_users, remote_tools, local_users, local_tools, words}`` for a change about to be made:
    who loses access to what. Counts are what this server knows (users seen recently, tools in its
    table and catalogs), never asked of peers."""
    svc = svc or _service()
    p = dict(params or {})
    out = {'net': net, 'kind': kind, 'remote_users': 0, 'remote_tools': 0, 'local_users': 0, 'local_tools': 0,
           'words': ''}
    if svc is None or net not in svc.runtimes:
        out['words'] = 'SAJHA Net is not running here: nothing changes.'
        return out
    if records is None:
        try:
            from sajha.net.integration.overview import read_net_audit
            records = read_net_audit(400)
        except Exception:
            records = []
    level = _s(p, 'level')
    target = _s(p, 'target_instance') or _s(p, 'instance') or _s(p, 'peer')
    if kind == 'block_add' and level == 'user':
        target = target or _s(p, 'user').rsplit('@', 1)[-1]
    who = 'every instance' if target == '*' else target
    inbound = outbound = False
    users_in: List[str] = []
    tools_out: List[str] = []
    if kind == 'block_add':
        if level in ('instance', 'inbound'):
            inbound = True
        if level in ('instance', 'outbound'):
            outbound = True
        if level == 'tool':
            if _s(p, 'direction') == 'outbound':
                tools_out = _remote_tools(svc, net, None, _s(p, 'tool'))
                local = _local_callers(records, net, None)
                out.update(local_users=len(local), local_tools=len(tools_out))
                out['words'] = (f'This server\'s users lose {len(tools_out)} remote tool(s) matching {_s(p, "tool")} '
                                f'({len(local)} of them called remote tools recently).')
                return out
            users_in = _remote_users(svc, net, target)
            out.update(remote_users=len(users_in), remote_tools=1)
            out['words'] = f'{who}\'s {len(users_in)} user(s) seen here lose the tool {_s(p, "tool")}.'
            return out
        if level == 'user':
            n = len(_exported_to(svc, net, target))
            out.update(remote_users=1, remote_tools=n)
            out['words'] = f'{_s(p, "user")} loses access to the {n} tool(s) this server offers {target}.'
            return out
    elif kind in ('revoke', 'sponsor_remove', 'forget_key'):
        inbound = outbound = True
    elif kind == 'unlink':
        ru = _s(p, 'remote_user')
        out.update(remote_users=1)
        out['words'] = (f'{ru} no longer runs as a linked local account; their next call is resolved by name matching '
                        f'or the unknown-user rule, or refused.')
        return out
    elif kind == 'trust' and _s(p, 'trust') == 'review':
        n = len(_remote_tools(svc, net, target))
        out.update(local_tools=n)
        out['words'] = f'{target}\'s {n} tool(s) here are held until approved, and changes to them later too.'
        return out
    elif kind == 'unapprove':
        out.update(local_tools=1)
        out['words'] = f'The tool {_s(p, "tool")} of {target} is held again until approved.'
        return out
    elif kind == 'block_remove':
        out['words'] = 'The block ends on the next request; what it refused or hid is allowed again.'
        return out
    if inbound:
        users_in = _remote_users(svc, net, target)
        exported = _exported_to(svc, net, target)
        out.update(remote_users=len(users_in), remote_tools=len(exported))
    if outbound:
        tools_out = _remote_tools(svc, net, target)
        local = _local_callers(records, net, target)
        out.update(local_tools=len(tools_out), local_users=len(local))
    parts = []
    if inbound:
        parts.append(f'{who}\'s {out["remote_users"]} user(s) seen here lose access to {out["remote_tools"]} tool(s) '
                     f'this server offers')
    if outbound:
        parts.append(f'This server\'s users lose {out["local_tools"]} tool(s) of {who} '
                     f'({out["local_users"]} called them recently)')
    out['words'] = ('; '.join(parts) + '.') if parts else 'Nothing this server knows of loses access.'
    return out
