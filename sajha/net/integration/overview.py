"""
The SAJHA Net console's overview and per-user views (design §17.1).

* :func:`overview_view`: one net as an administrator sees it: this server's identity there (admission
  mode, certificate, CA status), the members and their states, gossip health, open notices, contract
  conflicts and held tools, blocks, and from the audit chain the recent forwarded calls with their trace
  ids and outcomes, call-chain refusals and a summary of residency decisions.
* :func:`access_view`: what one signed-in user may use across the net: each plain name, every host
  offering it in resolution order, and which of those this server lets the user call.

Read-only and display-only: everything comes from the state store, this worker's registry and tables and
the audit chain, never from calling peers (design §17.3). Routing, residency and admission decide
nothing here; their own records are only summarised.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Refusal reasons that come from the call chain itself (design §14): hops, loops, the combined budget.
CHAIN_REASONS = ('hop_limit', 'loop', 'chain_limit')
#: Audit events of cross-instance calls (``net.call*`` at the home, ``net.host_*`` at the host).
CALL_EVENTS = ('net.call', 'net.call_attempt', 'net.host_call', 'net.host_refused')


def _service():
    from sajha.net.integration import get_service
    svc = get_service()
    return svc if svc is not None and svc.shared.enabled else None


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception as e:
        logger.debug(f'SAJHA Net overview: {e}')
        return default


def _rfc(ts) -> Optional[str]:
    from sajha.net.integration.console import _rfc as r
    return r(ts)


# ── the audit chain ─────────────────────────────────────────────────

def read_net_audit(limit: int = 400) -> List[Dict[str, Any]]:
    """The newest ``net.*`` records of the audit chain (flushed first), newest first."""
    from sajha.audit import get_writer
    from sajha.audit.chain import recent
    try:
        get_writer().flush()
    except Exception:
        pass
    from sqlalchemy import inspect
    from sajha.db.engine import get_engine
    eng = get_engine()
    if not inspect(eng).has_table('audit_chain'):
        return []
    return recent(eng, limit=limit, event='net.*')


def _activity(records: List[Dict[str, Any]], net: str, limit: int = 25) -> Dict[str, Any]:
    calls: List[Dict[str, Any]] = []
    chain: List[Dict[str, Any]] = []
    residency: Dict[str, Dict[str, int]] = {}
    residency_recent: List[Dict[str, Any]] = []
    outcomes: Dict[str, int] = {}
    for rec in records:
        ev = str(rec.get('event') or '')
        d = rec.get('details') if isinstance(rec.get('details'), dict) else {}
        rnet = d.get('net')
        if rnet and rnet != net:
            continue
        if ev == 'net.residency':
            key = f'{d.get("flow") or "?"}'
            row = residency.setdefault(key, {})
            out = str(d.get('outcome') or rec.get('outcome') or '?')
            row[out] = row.get(out, 0) + 1
            if out != 'allowed' and len(residency_recent) < 10:
                residency_recent.append({'at': rec.get('ts'), 'flow': d.get('flow'), 'outcome': out,
                                         'side': d.get('side'), 'instance': d.get('instance'), 'tool': d.get('tool'),
                                         'data_classes': d.get('data_classes') or [], 'rule': d.get('rule') or '',
                                         'trace_id': d.get('trace_id') or ''})
            continue
        if ev not in CALL_EVENTS:
            continue
        if ev == 'net.call' and not rnet and net and not _names_net(d, net):
            continue
        outcome = str(d.get('outcome') or rec.get('outcome') or '')
        side = 'host' if ev.startswith('net.host_') else 'home'
        other = d.get('host') if side == 'home' else (d.get('home') or d.get('peer'))
        row = {'at': rec.get('ts'), 'event': ev, 'side': side, 'trace_id': d.get('trace_id') or '',
               'tool': d.get('qualified_name') or d.get('name') or d.get('tool') or '', 'other': other or '',
               'outcome': outcome, 'attempt': d.get('attempt'), 'executed': d.get('executed'),
               'user': d.get('user') or ((rec.get('actor') or {}).get('user') if side == 'host' else '') or ''}
        if outcome in CHAIN_REASONS and len(chain) < limit:
            chain.append(row)
        if ev != 'net.call' and len(calls) < limit:
            calls.append(row)
        if ev in ('net.call_attempt', 'net.host_call', 'net.host_refused'):
            outcomes[outcome or '?'] = outcomes.get(outcome or '?', 0) + 1
    return {'calls': calls, 'chain_refusals': chain, 'outcomes': outcomes,
            'residency': {'by_flow': residency, 'recent': residency_recent}, 'scanned': len(records)}


def _names_net(d: Dict[str, Any], net: str) -> bool:
    """A home's unresolved ``net.call`` names its net only inside the resolution it records."""
    try:
        import json
        return f'"{net}"' in json.dumps(d.get('resolution') or {}) or f'{net}__' in str(d.get('name') or '')
    except Exception:
        return False


# ── one net, for an administrator ───────────────────────────────────

def _gossip_health(node, members: List[Dict[str, Any]], st: Dict[str, Any]) -> Dict[str, Any]:
    if node is None:
        return {'state': 'not running', 'words': 'the net is not running on this server', 'level': 'bad'}
    if node.refused():
        return {'state': 'name conflict', 'words': 'every member refuses this server under its name', 'level': 'bad'}
    if not node.joined():
        return {'state': 'not joined', 'level': 'bad',
                'words': 'no seed or saved peer answered yet' + (f'; retrying in {int(st.get("backoff") or 0)} s'
                                                                  if st.get('backoff') else '')}
    bad = [m['name'] for m in members if m['state'] in ('suspect', 'dead')]
    if not members:
        return {'state': 'net of one', 'level': 'solo', 'words': 'joined; no other member yet'}
    if bad:
        return {'state': 'degraded', 'level': 'warn', 'words': f'{len(bad)} of {len(members)} members suspect or dead'}
    return {'state': 'healthy', 'level': 'ok', 'words': f'joined; all {len(members)} other members alive'}


def overview_view(net: Optional[str] = None, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """``{enabled, nets: [names], net: {...} | None}`` for ``net`` (the first configured one by default).
    ``records``: audit records to summarise (default: the newest ``net.*`` records of the chain)."""
    svc = _service()
    if svc is None:
        from sajha.net.integration.console import self_identity
        ident = self_identity()
        return {'enabled': False, 'nets': [s['net'] for s in ident], 'net': None,
                'self': ident[0] if ident else None}
    names = list(svc.runtimes)
    if not names:
        return {'enabled': True, 'nets': [], 'net': None}
    name = net if net in svc.runtimes else names[0]
    rt = svc.runtimes[name]
    cfg, node = rt.cfg, rt.node
    status = next((n for n in _safe(svc.status, {}).get('nets', []) if n.get('net') == name), {})
    members = status.get('members') or []
    st = _safe(node.status, {}) if node is not None else {}
    counts: Dict[str, int] = {s: 0 for s in ('alive', 'suspect', 'dead', 'left')}
    for m in members:
        counts[m['state']] = counts.get(m['state'], 0) + 1
    out: Dict[str, Any] = {
        'net': name, 'instance': cfg.instance_name or 'this server', 'url': cfg.base_url, 'region': cfg.region,
        'labels': dict(cfg.labels or {}), 'founder': cfg.founder, 'error': rt.error,
        'admission': cfg.admission, 'membership': cfg.membership, 'require_https': cfg.require_https,
        'seeds': list(cfg.seeds), 'runtime_seeds': _safe(lambda: svc.runtime_seeds(name), []),
        'certificate': status.get('certificate'), 'incarnation': status.get('incarnation'),
        'revocations': status.get('revocations'), 'agent': status.get('agent'),
        'joined': bool(status.get('joined')), 'refused': status.get('refused'),
        'members': members, 'counts': counts,
        'gossip': dict(_gossip_health(node, members, st), joined_at=_rfc(st.get('joined_at')),
                       joined_via=st.get('joined_via') or '', last_errors=st.get('last_errors') or [],
                       interval_ms=cfg.gossip.gossip_interval_ms,
                       suspect_timeout_seconds=cfg.gossip.suspect_timeout_seconds,
                       gossiping=bool(node is not None and _safe(lambda: node.gossiping, False))),
    }
    # admission: what this mode remembers or holds
    adm: Dict[str, Any] = {'mode': cfg.admission}
    if cfg.admission == 'open':
        adm['first_use'] = [{'instance': k, 'thumbprint': v}
                            for k, v in sorted(_safe(lambda: svc.first_use_keys(name), {}).items())]
    elif cfg.admission == 'manual':
        adm['pins'] = [{'thumbprint': p, 'source': 'configuration'} for p in (cfg.identity.pins or [])] + \
                      [{'thumbprint': p, 'source': 'runtime'} for p in _safe(lambda: svc.runtime_pins(name), [])]
    elif cfg.admission == 'builtin_ca':
        adm['ca'] = {'enabled': bool(cfg.ca.enabled), 'initialised': rt.ca is not None}
        if rt.ca is not None:
            v = _safe(lambda: svc.ca_view(name), None)
            if v:
                adm['ca'].update(thumbprint=v.get('thumbprint'), issued=len(v.get('issued') or []),
                                 pending_tokens=len(v.get('pending_tokens') or []),
                                 revoked=len((v.get('revocation_list') or {}).get('revoked') or []),
                                 revocation_version=(v.get('revocation_list') or {}).get('version'))
    out['admission_detail'] = adm
    # the map's fallback while the topology endpoint answers nothing: the members, without links
    out['fallback_topology'] = {
        'name': name, 'edges': [],
        'nodes': [{'name': out['instance'], 'kind': cfg.kind, 'region': cfg.region, 'state': 'alive', 'self': True}] +
                 [{'name': m['name'], 'kind': m.get('kind') or 'sajha', 'region': m.get('region') or '',
                   'state': m['state'], 'self': False} for m in members]}
    # notices of this net (open and acknowledged)
    try:
        from sajha import notices
        ns = [n for n in notices.list_notices(state='open', source='sajhanet')
              if f':{name}' in str(n.get('id') or '') or str(n.get('id') or '').endswith(name)]
    except Exception:
        ns = []
    out['notices'] = [{'id': n.get('id'), 'severity': n.get('severity'), 'title': n.get('title'),
                       'detail': n.get('detail') or '', 'state': n.get('state')} for n in ns]
    # catalogs: conflicts, warnings, held tools, remote tool counts
    c = getattr(svc, 'catalogs', None)
    conf = _safe(lambda: c.conflicts(name)['nets'].get(name) or {}, {}) if c is not None else {}
    out['quarantined'] = [dict(r, tool=t) for t, r in sorted((conf.get('quarantined') or {}).items())]
    out['warnings'] = conf.get('warnings') or []
    rows = _safe(lambda: [r for r in c.router.rows() if r['net'] == name], []) if c is not None and c.router else []
    by_state: Dict[str, int] = {}
    for r in rows:
        by_state[r['state']] = by_state.get(r['state'], 0) + 1
    out['remote_tools'] = by_state
    out['held'] = [{'peer': r['host_instance'], 'tool': r['host_tool'], 'qualified_name': r['qualified_name'],
                    'version': r.get('version') or '', 'problem': r.get('problem') or ''}
                   for r in rows if r['state'] == 'held']
    out['router_counters'] = {f'{k[0]}:{k[1]}': v for k, v in sorted(_safe(lambda: dict(c.router.counters), {}).items())
                              if isinstance(k, tuple) and len(k) == 2} if c is not None and c.router else {}
    # blocks
    a = getattr(svc, 'authz', None)
    bv = _safe(lambda: a.blocks_view(name), None) if a is not None and name in getattr(a, 'nets', {}) else None
    out['blocks'] = {'mine': (bv or {}).get('blocks') or [], 'published': (bv or {}).get('published') or {},
                     'available': bv is not None}
    # the audit chain: forwarded calls, chain refusals, residency decisions
    if records is None:
        records = _safe(read_net_audit, [])
    out['activity'] = _activity(records or [], name)
    return {'enabled': True, 'nets': names, 'net': out}


# ── what one user may use across the net ────────────────────────────

def access_view(auth=None) -> Dict[str, Any]:
    """Per net: every plain name of a remote tool with its hosts in resolution order and whether this
    server lets ``auth`` call each, plus this user's local tool count. The host decides again on every
    call (design §11.1); quarantined and blocked copies are listed with their state, never as usable."""
    from sajha.net.integration.console import LISTED, _local_tools, _may_use, instances_view
    svc = _service()
    local = [t.name for t in _local_tools()]
    mine_local = [n for n in local if _may_use(auth, n)]
    nets: List[Dict[str, Any]] = []
    if svc is None:
        for n in instances_view(auth)['nets']:
            nets.append({'net': n['net'], 'instance': n['instance'], 'tools': [], 'usable': 0, 'listed': 0})
        return {'enabled': False, 'local_total': len(local), 'local_usable': len(mine_local), 'nets': nets}
    c = getattr(svc, 'catalogs', None)
    rows = _safe(lambda: c.router.rows(), []) if c is not None and c.router is not None else []
    aliases = _safe(lambda: c.router.aliases(), {}) if c is not None and c.router is not None else {}
    order_of = {q: i for qs in aliases.values() for i, q in enumerate(qs)}
    alias_of = {q: p for p, qs in aliases.items() for q in qs}
    states = {}
    for net, rt in svc.runtimes.items():
        if rt.node is not None:
            states[net] = {m['name']: m['state'] for m in _safe(rt.node.members, [])}
    for net, rt in svc.runtimes.items():
        groups: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            if r['net'] != net:
                continue
            g = groups.setdefault(r['part'], {'name': r['part'], 'alias': '', 'local': r['part'] in local,
                                              'hosts': []})
            if alias_of.get(r['qualified_name']):
                g['alias'] = alias_of[r['qualified_name']]
            usable = r['state'] in LISTED and _may_use(auth, r['qualified_name'])
            g['hosts'].append({'instance': r['host_instance'], 'qualified_name': r['qualified_name'],
                               'state': r['state'], 'member_state': states.get(net, {}).get(r['host_instance'], ''),
                               'usable': usable, 'try_it': r['qualified_name'] if usable and r['state'] == 'active' else '',
                               'order': order_of.get(r['qualified_name'])})
        tools = []
        for g in sorted(groups.values(), key=lambda g: g['name']):
            g['hosts'].sort(key=lambda h: (h['order'] is None, h['order'] if h['order'] is not None else 0, h['instance']))
            g['usable_hosts'] = sum(1 for h in g['hosts'] if h['usable'])
            tools.append(g)
        nets.append({'net': net, 'instance': rt.cfg.instance_name or 'this server', 'tools': tools,
                     'usable': sum(1 for g in tools if g['usable_hosts']), 'listed': len(tools)})
    return {'enabled': True, 'local_total': len(local), 'local_usable': len(mine_local), 'nets': nets}
