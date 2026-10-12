# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The data behind the SAJHA Net console's management pages (design §17.1), for administrators:

* :func:`instance_admin` — an instance's tabs beyond its tools: traffic, users, keys, blocks, history.
* :func:`reviews_view` — the conflicts and reviews queue (what needs a person).
* :func:`users_page` — remote users per instance, how each resolved, links, role maps, name matching.
* :func:`blocks_page` — the access and blocks matrix (callers × hosts) and the list of blocks.
* :func:`keys_page` — the net key directory per home and, for one home, its records.
* :func:`activity_view`, :func:`trace_view` — live cross-instance calls from the audit chain; one call's records.
* :func:`certificates_view` — this server's certificate per net and, on a CA instance, issued certificates,
  waiting tokens and the revocation list.
* :func:`settings_view` — nets in preference order, names, seeds, gossip health, routing preferences, defaults.
* :func:`sponsored_view` — the plain MCP servers this server sponsors, with the upstreams it could sponsor.
* :func:`snapshots_view`, :func:`snapshot_diff`, :func:`snapshot_restore` — the signed snapshots.

Read-only (changes go through :mod:`sajha.net.integration.changes`): everything comes from the state store,
the storage backend, this worker's registry and tables and the audit chain, never from calling peers
(design §17.3). Database sessions are opened only around their query and closed before anything slow.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _service():
    from sajha.net.integration import get_service
    svc = get_service()
    return svc if svc is not None and svc.shared.enabled else None


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception as e:
        logger.debug(f'SAJHA Net console: {e}')
        return default


def _pick(svc, net: Optional[str]) -> Optional[str]:
    names = list(svc.runtimes) if svc is not None else []
    if not names:
        return None
    return net if net in svc.runtimes else names[0]


def _base(net: Optional[str]) -> Dict[str, Any]:
    """``{enabled, nets, net}`` with the chosen net (the first configured by default)."""
    svc = _service()
    if svc is None:
        from sajha.net.integration.console import self_identity
        return {'enabled': False, 'nets': [s['net'] for s in self_identity()], 'net': None}
    return {'enabled': True, 'nets': list(svc.runtimes), 'net': _pick(svc, net)}


def _records(records: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if records is not None:
        return records
    from sajha.net.integration.overview import read_net_audit
    return _safe(lambda: read_net_audit(400), [])


def _members(svc, net: str) -> List[Dict[str, Any]]:
    st = next((n for n in _safe(svc.status, {}).get('nets', []) if n.get('net') == net), {})
    return st.get('members') or []


def _rows(svc, net: str) -> List[Dict[str, Any]]:
    c = getattr(svc, 'catalogs', None)
    if c is None or c.router is None:
        return []
    return [r for r in _safe(c.router.rows, []) if r['net'] == net]


def _authz_state(svc, net: str):
    a = getattr(svc, 'authz', None)
    return a, (a.nets.get(net) if a is not None else None)


def _detail(rec: Dict[str, Any]) -> Dict[str, Any]:
    return rec.get('details') if isinstance(rec.get('details'), dict) else {}


# ── calls from the audit chain ──────────────────────────────────────

CALL_EVENTS = ('net.call_attempt', 'net.host_call', 'net.host_refused')


def call_rows(records: List[Dict[str, Any]], net: Optional[str]) -> List[Dict[str, Any]]:
    """One row per attempt at this home and per call served here, newest first."""
    out = []
    for rec in records:
        ev = str(rec.get('event') or '')
        if ev not in CALL_EVENTS:
            continue
        d = _detail(rec)
        if net and d.get('net') and d.get('net') != net:
            continue
        side = 'host' if ev.startswith('net.host_') else 'home'
        other = d.get('host') if side == 'home' else (d.get('home') or d.get('peer'))
        user = d.get('user') or (rec.get('actor') or {}).get('user') or ''
        outcome = str(d.get('outcome') or rec.get('outcome') or '')
        out.append({'at': rec.get('ts'), 'event': ev, 'side': side, 'other': other or '',
                    'from': (other or '') if side == 'host' else '', 'to': (other or '') if side == 'home' else '',
                    'tool': d.get('qualified_name') or d.get('local_tool') or d.get('tool') or d.get('name') or '',
                    'outcome': outcome, 'ok': outcome in ('ok', 'answered', 'success', ''),
                    'attempt': d.get('attempt'), 'executed': d.get('executed'), 'user': str(user),
                    'trace_id': d.get('trace_id') or '', 'mapping': d.get('mapping') or '',
                    'streamed': bool(d.get('streamed')), 'net': d.get('net') or net or ''})
    return out


# ── an instance's tabs ──────────────────────────────────────────────

TABS = ('tools', 'traffic', 'users', 'keys', 'blocks', 'history')


def instance_admin(net: str, instance: str, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The administrator's tabs of one member (not this server): what it is, what flows each way,
    its users here, its key records, the blocks between us, and the changes that named it."""
    svc = _service()
    out: Dict[str, Any] = {'net': net, 'instance': instance, 'enabled': svc is not None and net in svc.runtimes}
    if not out['enabled']:
        return out
    m = next((x for x in _members(svc, net) if x.get('name') == instance), None)
    out['member'] = m or {}
    c = getattr(svc, 'catalogs', None)
    # tools both ways
    out['tools_in'] = [{'qualified_name': r['qualified_name'], 'tool': r['host_tool'], 'state': r['state'],
                        'trust': r.get('trust') or '', 'version': r.get('version') or '',
                        'contract_hash': r.get('contract_hash') or ''} for r in _rows(svc, net)
                       if r['host_instance'] == instance]
    book = c.books.get(net) if c is not None else None
    out['tools_out'] = sorted(t['name'] for t in _safe(lambda: book.exports(instance), [])) if book else []
    level, pinned = _safe(lambda: c.trust_of(net, instance), ('auto', [])) if c is not None else ('auto', [])
    out['trust'] = {'level': level, 'pinned': pinned}
    # traffic
    rows = [r for r in call_rows(_records(records), net) if r['other'] == instance]
    by_outcome: Dict[str, Dict[str, int]] = {'home': {}, 'host': {}}
    for r in rows:
        b = by_outcome[r['side']]
        b[r['outcome'] or '?'] = b.get(r['outcome'] or '?', 0) + 1
    lat = _safe(lambda: c.router.latency_p50(net, instance), None) if c is not None and c.router else None
    out['traffic'] = {'to': sum(by_outcome['home'].values()), 'from': sum(by_outcome['host'].values()),
                      'outcomes': by_outcome, 'latency_p50_ms': int(lat) if lat is not None else None,
                      'recent': rows[:25]}
    # users
    a, st = _authz_state(svc, net)
    if st is not None:
        uv = _safe(lambda: a.users_view(net), {})
        out['users'] = {'seen': [u for u in uv.get('seen') or [] if u.get('home') == instance],
                        'links': {k: v for k, v in (uv.get('links') or {}).items() if k.endswith('@' + instance)},
                        'role_map': (uv.get('role_maps') or {}).get(instance) or {},
                        'name_matching': instance not in set(uv.get('no_name_match') or []),
                        'match_by_name': uv.get('match_by_name'), 'unknown': uv.get('unknown')}
        kv = _safe(lambda: a.keys_view(net, instance), {})
        out['keys'] = {'summary': next((h for h in kv.get('homes') or [] if h.get('home') == instance), None),
                       'records': kv.get('records') or []}
        bv = _safe(lambda: a.blocks_view(net), {})
        out['blocks'] = {'mine': [b for b in bv.get('blocks') or []
                                  if b.get('target_instance') in (instance, '*')
                                  or str(b.get('user') or '').endswith('@' + instance)],
                         'theirs': [b for b in (bv.get('published') or {}).get(instance) or []
                                    if b.get('target_instance') in (bv.get('instance'), '*')
                                    or str(b.get('user') or '').endswith('@' + str(bv.get('instance')))]}
    from sajha.net.integration.changes import history
    out['history'] = history(net, instance=instance, limit=50, svc=svc)
    return out


# ── conflicts and reviews ───────────────────────────────────────────

def reviews_view(net: Optional[str] = None) -> Dict[str, Any]:
    """What needs a person in one net: quarantined names, description warnings, tools held for review,
    this server's own name conflict and those seen, own tools refused for their published name, and
    catalogs flagged at their last pull."""
    out = _base(net)
    svc = _service()
    name = out['net']
    if svc is None or name is None:
        out.update(items=[], counts={})
        return out
    c = getattr(svc, 'catalogs', None)
    rt = svc.runtimes[name]
    items: List[Dict[str, Any]] = []
    conf = _safe(lambda: c.conflicts(name)['nets'].get(name) or {}, {}) if c is not None else {}
    rows = _rows(svc, name)
    for tool, r in sorted((conf.get('quarantined') or {}).items()):
        offers = []
        for o in (r.get('offers') or []) if isinstance(r.get('offers'), list) else []:
            inst = o.get('instance') or o.get('host') or ''
            q = next((x['qualified_name'] for x in rows if x['host_instance'] == inst and x['part'] == tool), '')
            offers.append({'instance': inst, 'contract_hash': o.get('contract_hash') or '', 'qualified_name': q,
                           'self': inst == rt.cfg.instance_name})
        items.append({'kind': 'conflict', 'severity': 'error', 'tool': tool, 'offers': offers,
                      'since': r.get('since') or '', 'detail': r.get('text') or r.get('pointer') or '',
                      'agreeing': r.get('agreeing') or [], 'differing': r.get('differing') or []})
    for w in conf.get('warnings') or []:
        items.append({'kind': 'description', 'severity': 'warning', 'tool': w.get('tool'), 'hosts': w.get('hosts') or []})
    for r in rows:
        if r['state'] == 'held':
            items.append({'kind': 'held', 'severity': 'warning', 'tool': r['host_tool'], 'peer': r['host_instance'],
                          'qualified_name': r['qualified_name'], 'version': r.get('version') or '',
                          'problem': r.get('problem') or ''})
    node = rt.node
    if node is not None and _safe(node.refused, None):
        ref = node.refused() or {}
        items.append({'kind': 'name', 'severity': 'error', 'tool': '', 'instance': rt.cfg.instance_name,
                      'detail': f'held by {ref.get("holder_url") or "another participant"} '
                                f'({ref.get("holder_state") or ""})'})
    try:
        from sajha import notices
        for n in notices.list_notices(state='open', source='sajhanet'):
            nid = str(n.get('id') or '')
            if nid.startswith(f'sajhanet.name_conflict_seen:{name}:'):
                items.append({'kind': 'name', 'severity': 'warning', 'tool': '', 'instance': nid.rsplit(':', 1)[-1],
                              'detail': n.get('title') or ''})
    except Exception:
        pass
    book = c.books.get(name) if c is not None else None
    for local, r in sorted(((getattr(book, 'refused', None) or {}) if book is not None else {}).items()):
        items.append({'kind': 'refused', 'severity': 'warning', 'tool': local, 'published': r.get('published'),
                      'detail': r.get('reason') or ''})
    for peer, h in sorted((_safe(lambda: book.status(), {}).get('peers') or {}).items() if book is not None else []):
        if h.get('flags'):
            items.append({'kind': 'flagged', 'severity': 'warning', 'tool': '', 'peer': peer,
                          'flags': list(h.get('flags') or [])})
    counts: Dict[str, int] = {}
    for i in items:
        counts[i['kind']] = counts.get(i['kind'], 0) + 1
    out.update(items=items, counts=counts)
    return out


# ── users across the net ────────────────────────────────────────────

def users_page(net: Optional[str] = None, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    out = _base(net)
    svc = _service()
    name = out['net']
    if svc is None or name is None:
        out.update(instances=[], available=False)
        return out
    a, st = _authz_state(svc, name)
    if st is None:
        out.update(instances=[], available=False)
        return out
    uv = _safe(lambda: a.users_view(name), {})
    last: Dict[str, Dict[str, Any]] = {}
    for r in call_rows(_records(records), name):
        if r['side'] == 'host' and r['user'] and r['user'] not in last:
            last[r['user']] = {'at': r['at'], 'tool': r['tool'], 'outcome': r['outcome']}
    homes = sorted({m['name'] for m in _members(svc, name)} | {u.get('home') for u in uv.get('seen') or []
                                                                if u.get('home')}
                   | {k.rsplit('@', 1)[1] for k in uv.get('links') or {} if '@' in k})
    no_match = set(uv.get('no_name_match') or [])
    maps = uv.get('role_maps') or {}
    insts = []
    for h in homes:
        seen = [dict(u, last=last.get(u.get('user'))) for u in uv.get('seen') or [] if u.get('home') == h]
        links = [{'remote_user': k, **(v if isinstance(v, dict) else {'local': v})}
                 for k, v in sorted((uv.get('links') or {}).items()) if k.endswith('@' + h)]
        insts.append({'instance': h, 'seen': seen, 'links': links, 'name_matching': h not in no_match,
                      'role_map': maps.get(h) or {}})
    out.update(available=True, instances=insts, defaults={
        'match_by_name': uv.get('match_by_name'), 'unknown': uv.get('unknown'), 'remote_admin': uv.get('remote_admin'),
        'exclude_names': uv.get('exclude_names') or [], 'role_map_all': maps.get('*') or {}})
    return out


# ── access and blocks ───────────────────────────────────────────────

def _cell(blocks_by_host: Dict[str, List[Dict[str, Any]]], caller: str, host: str) -> Dict[str, Any]:
    """What stops ``caller`` from calling ``host``'s tools, from the blocks each side set."""
    def names(b, who):
        return b.get('target_instance') in (who, '*')
    at_host = [b for b in blocks_by_host.get(host, []) if names(b, caller)]
    at_caller = [b for b in blocks_by_host.get(caller, []) if names(b, host)]
    if any(b['level'] == 'instance' for b in at_host + at_caller):
        state = 'blocked'
    elif any(b['level'] == 'inbound' for b in at_host):
        state = 'inbound'
    elif any(b['level'] == 'outbound' for b in at_caller):
        state = 'outbound'
    elif any(b['level'] in ('tool', 'user') for b in at_host) or \
            any(b['level'] == 'tool' and b.get('direction') == 'outbound' for b in at_caller):
        state = 'partial'
    else:
        state = 'allowed'
    return {'state': state, 'by': sorted({x for x in ([host] if at_host else []) + ([caller] if at_caller else [])})}


def blocks_page(net: Optional[str] = None) -> Dict[str, Any]:
    out = _base(net)
    svc = _service()
    name = out['net']
    if svc is None or name is None:
        out.update(available=False, matrix=None, mine=[], published={})
        return out
    a, st = _authz_state(svc, name)
    if st is None:
        out.update(available=False, matrix=None, mine=[], published={})
        return out
    bv = _safe(lambda: a.blocks_view(name), {'blocks': [], 'published': {}, 'instance': ''})
    me = bv.get('instance') or st.me
    mine = bv.get('blocks') or []
    published = bv.get('published') or {}
    members = [m['name'] for m in _members(svc, name)]
    insts = [me] + sorted(members)
    by_host = {me: [b for b in mine if b.get('active', True)]}
    for peer, bl in published.items():
        by_host[peer] = list(bl)
    rows = [{'caller': c, 'cells': [dict(_cell(by_host, c, h), host=h) if c != h else {'state': 'self', 'host': h, 'by': []}
                                    for h in insts]} for c in insts]
    out.update(available=True, instance=me, instances=insts, matrix=rows, mine=mine, published=published,
               version=bv.get('version'), members=members)
    return out


# ── the key directory ───────────────────────────────────────────────

def keys_page(net: Optional[str] = None, home: str = '') -> Dict[str, Any]:
    out = _base(net)
    svc = _service()
    name = out['net']
    if svc is None or name is None:
        out.update(available=False, homes=[], records=[], home='')
        return out
    a, st = _authz_state(svc, name)
    if st is None:
        out.update(available=False, homes=[], records=[], home='')
        return out
    kv = _safe(lambda: a.keys_view(name, home or None), {})
    from sajha.net.integration.console import _rfc
    for h in kv.get('homes') or []:
        h['last_received_at'] = _rfc(h.get('last_received'))
    out.update(available=True, instance=kv.get('instance') or st.me, homes=kv.get('homes') or [],
               records=kv.get('records') or [], home=home)
    return out


# ── live activity ───────────────────────────────────────────────────

def activity_view(net: Optional[str] = None, instance: str = '', user: str = '', tool: str = '', outcome: str = '',
                  since: str = '', limit: int = 100, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Cross-instance calls, newest first, filtered; ``since`` (a record timestamp) returns only newer ones."""
    out = _base(net)
    svc = _service()
    name = out['net']
    me = svc.runtimes[name].cfg.instance_name if svc is not None and name else ''
    rows = call_rows(_records(records), name) if name else []

    def keep(r):
        if instance and r['other'] != instance:
            return False
        if user and user.lower() not in r['user'].lower():
            return False
        if tool and tool.lower() not in r['tool'].lower():
            return False
        if outcome == 'refused' and r['ok']:
            return False
        if outcome == 'ok' and not r['ok']:
            return False
        if since and str(r['at'] or '') <= since:
            return False
        return True
    rows = [r for r in rows if keep(r)][:max(1, min(int(limit or 100), 500))]
    for r in rows:
        r['from'] = r['other'] if r['side'] == 'host' else me
        r['to'] = me if r['side'] == 'host' else r['other']
    out.update(instance=me, calls=rows, newest=rows[0]['at'] if rows else since,
               members=[m['name'] for m in _members(svc, name)] if svc is not None and name else [])
    return out


def trace_view(trace_id: str, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """This side's audit records of one call (every ``net.*`` record with that trace id), and where the
    other side's records are (each other instance's console)."""
    trace_id = (trace_id or '').strip()
    recs = [r for r in _records(records) if trace_id and _detail(r).get('trace_id') == trace_id]
    svc = _service()
    others = []
    if svc is not None:
        seen = set()
        for r in recs:
            d = _detail(r)
            peer = d.get('host') or d.get('home') or d.get('peer')
            net = d.get('net')
            if not peer or (net, peer) in seen or net not in svc.runtimes:
                continue
            seen.add((net, peer))
            m = next((x for x in _members(svc, net) if x.get('name') == peer), None)
            if m and m.get('url'):
                others.append({'net': net, 'instance': peer,
                               'url': m['url'].rstrip('/') + '/admin/sajhanet/activity?trace=' + trace_id})
    return {'trace_id': trace_id, 'records': recs, 'others': others}


# ── certificates ────────────────────────────────────────────────────

def certificates_view() -> Dict[str, Any]:
    svc = _service()
    if svc is None:
        return {'enabled': False, 'nets': []}
    status = {n.get('net'): n for n in _safe(svc.status, {}).get('nets', [])}
    nets = []
    for name, rt in svc.runtimes.items():
        s = status.get(name, {})
        item: Dict[str, Any] = {'net': name, 'instance': rt.cfg.instance_name, 'admission': rt.cfg.admission,
                                'certificate': s.get('certificate'), 'revocations': s.get('revocations'),
                                'ca_enabled': bool(rt.cfg.ca.enabled), 'ca': None, 'error': rt.error or ''}
        if rt.ca is not None:
            v = _safe(lambda name=name: svc.ca_view(name), None)
            if v:
                revoked = v.get('revocation_list') or {}
                rs = {e.get('serial') for e in revoked.get('revoked') or [] if e.get('serial')}
                ri = {e.get('instance') for e in revoked.get('revoked') or [] if e.get('instance')}
                issued = [dict(c, revoked=c.get('serial') in rs or c.get('instance') in ri) for c in v.get('issued') or []]
                from sajha.net import crypto
                item['ca'] = {'thumbprint': v.get('thumbprint'), 'issued': issued,
                              'pending_tokens': [dict(t, expires_at=_safe(lambda t=t: crypto.rfc3339(float(t['expires'])),
                                                                          t.get('expires')))
                                                 for t in v.get('pending_tokens') or []],
                              'revocation_list': revoked}
        nets.append(item)
    return {'enabled': True, 'nets': nets}


# ── settings ────────────────────────────────────────────────────────

def settings_view() -> Dict[str, Any]:
    svc = _service()
    if svc is None:
        from sajha.net.integration.console import self_identity
        return {'enabled': False, 'nets': [{'net': s['net'], 'instance': s['instance'], 'region': s['region'],
                                            'labels': s['labels'], 'default_name': s['net'] == 'default'}
                                           for s in self_identity()], 'routing': {}, 'defaults': {}}
    from sajha.net.integration.overview import _gossip_health
    status = {n.get('net'): n for n in _safe(svc.status, {}).get('nets', [])}
    nets = []
    for name, rt in svc.runtimes.items():
        cfg, node = rt.cfg, rt.node
        s = status.get(name, {})
        members = s.get('members') or []
        nets.append({'net': name, 'instance': cfg.instance_name, 'region': cfg.region, 'labels': dict(cfg.labels or {}),
                     'url': cfg.base_url, 'admission': cfg.admission, 'certificate': s.get('certificate'),
                     'seeds': list(cfg.seeds), 'runtime_seeds': _safe(lambda name=name: svc.runtime_seeds(name), []),
                     'gossip': _gossip_health(node, members, _safe(node.status, {}) if node is not None else {}),
                     'default_name': name == 'default', 'error': rt.error or '', 'require_https': cfg.require_https})
    c = getattr(svc, 'catalogs', None)
    routing: Dict[str, Any] = {}
    if c is not None:
        rows = _safe(lambda: c.router.rows(), []) if c.router is not None else []
        prefs = []
        for tool, entries in sorted((c.settings.preferences or {}).items()):
            checked = []
            for e in entries:
                if '/' in e:
                    n, i = e.split('/', 1)
                    hit = any(r['net'] == n and r['host_instance'] == i and r['part'] == tool for r in rows)
                else:
                    hit = e in svc.runtimes
                checked.append({'entry': e, 'matches': bool(hit)})
            prefs.append({'tool': tool, 'entries': checked,
                          'known': any(r['part'] == tool for r in rows) or tool in _safe(c._local_names, [])})
        routing = {'preferences': prefs, 'max_fallbacks': c.settings.max_fallbacks,
                   'bare_aliases': c.settings.bare_aliases, 'routing': c.settings.routing,
                   'default_trust': c.settings.default_trust, 'max_hops': c.settings.max_hops,
                   'max_call_chain': c.settings.max_call_chain}
    defaults: Dict[str, Any] = {}
    a = getattr(svc, 'authz', None)
    if a is not None and a.nets:
        st = next(iter(a.nets.values()))
        u = st.settings.users
        defaults = {'match_by_name': u.match_by_name, 'unknown': u.unknown, 'remote_admin': u.remote_admin,
                    'user_identity': st.settings.user_identity}
    return {'enabled': True, 'nets': nets, 'routing': routing, 'defaults': defaults}


# ── sponsored servers ───────────────────────────────────────────────

def _upstreams() -> List[str]:
    try:
        from sajha.app import tools_registry as reg
        from sajha.federation.tool import FederatedTool
        with reg._tools_lock:
            items = list(reg.tools.values())
        return sorted({t.upstream_id for t in items if isinstance(t, FederatedTool) and getattr(t, 'upstream_id', '')})
    except Exception:
        return []


def sponsored_view() -> Dict[str, Any]:
    svc = _service()
    if svc is None:
        return {'enabled': False, 'sponsored': [], 'nets': [], 'upstreams': _upstreams()}
    from sajha.net.integration.sponsored import get_sponsorships
    rows = _safe(lambda: get_sponsorships(svc).view(), [])
    return {'enabled': True, 'sponsored': rows, 'nets': list(svc.runtimes), 'upstreams': _upstreams()}


# ── snapshots ───────────────────────────────────────────────────────

def _snap():
    from sajha.snapshots import get_service
    return get_service()


def snapshots_view(verify: bool = True) -> Dict[str, Any]:
    """Every retained snapshot (oldest first): time, size, section counts, chain and signature status."""
    from sajha.snapshots.core import iter_sections
    s = _snap()
    store = s.store
    report = _safe(lambda: store.verify(), {'ok': None, 'snapshots': [], 'problems': [], 'notes': []}) if verify \
        else {'ok': None, 'snapshots': [], 'problems': [], 'notes': []}
    checked = {e['name']: e for e in report.get('snapshots') or []}
    items = []
    for n in store.names():
        row: Dict[str, Any] = {'name': n, 'size': _safe(lambda n=n: store.path(n).stat().st_size, 0)}
        try:
            env = store.load(n)
            b = env['snapshot']
            row.update(seq=b.get('seq'), created=b.get('created'), sections=dict(iter_sections(b)),
                       sha256=str(env.get('sha256') or '')[:16])
        except Exception as e:
            row['error'] = str(e)
        e = checked.get(n)
        if e is not None:
            probs = e.get('problems') or []
            row['chain'] = 'verified' if e.get('ok') else 'broken'
            row['signature'] = 'problem' if any('signature' in p or 'signed with' in p for p in probs) else 'verified'
            row['problems'] = probs
        items.append(row)
    return {'status': _safe(s.status, {}), 'snapshots': items, 'ok': report.get('ok'),
            'problems': report.get('problems') or [], 'notes': report.get('notes') or []}


def snapshot_diff(a: str, b: str) -> Dict[str, Any]:
    from sajha.snapshots.core import diff, diff_lines
    store = _snap().store
    na, nb = store.resolve(a), store.resolve(b)
    d = diff(store.load(na), store.load(nb))
    return {'a': na, 'b': nb, 'diff': d, 'lines': diff_lines(d)}


def snapshot_restore(name: str, keys: bool = True, dry_run: bool = True, session_factory=None) -> Dict[str, Any]:
    """Plan (``dry_run``) or apply a restore of the roles, users and persistent key records a verified
    snapshot holds and the database lacks. The session is opened for the restore only and always closed."""
    from sajha.snapshots.core import restore
    store = _snap().store
    n = store.resolve(name)
    report = store.verify()
    entry = next((s for s in report['snapshots'] if s['name'] == n), None)
    if entry is None or not entry.get('ok'):
        from sajha.net.integration import ServiceError
        raise ServiceError(409, f'{n} does not verify: ' + '; '.join((entry or {}).get('problems') or ['not found']))
    env = store.load(n)
    if session_factory is None:
        from sajha.db.engine import get_db_session as session_factory
    db = session_factory()
    try:
        plan = restore(db, env, keys=keys, dry_run=dry_run)
    finally:
        db.close()
    return {'name': n, 'dry_run': dry_run, 'plan': plan}
