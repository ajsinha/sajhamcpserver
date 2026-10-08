"""
SAJHA Net in the web console (design §17): the Instances page for every signed-in user, the navbar
badge, and the views behind the admin's Remote tools page.

* :func:`instances_view`: every participant of every net this server is in (this server always
  included, as a net of one when SAJHA Net is off or the net has no other member), with kind,
  region, labels, state and last seen, and how many of its tools the signed-in user may use here.
* :func:`instance_view`: one participant and the tools it offers this user (for this server, its
  own tools), each with alias, description, inputs and outputs, health and latency.
* :func:`badge`: the navbar's "Net · <instance name>" (one net) or "Nets · <count>" with a health dot.

Read-only: everything comes from the state store and this worker's registry, never from calling
peers (design §17.3). "May use" is this server's own decision (tool access and visibility); the host
decides again on every call (design §11.1).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LISTED = ('active', 'unavailable')


# ── who this server is ──────────────────────────────────────────────

_self_cache: Dict[str, Any] = {'at': 0.0, 'value': None}


def _settings_host_port():
    try:
        from sajha.core.config import get_settings
        st = get_settings()
        return str(st.server_host), int(st.server_port)
    except Exception:
        return '0.0.0.0', 3002


def self_identity() -> List[Dict[str, Any]]:
    """This server's net and instance name in each configured net, from configuration (a net named
    ``default`` when none is listed). Used when SAJHA Net is off or a net is not running: the
    server is then a net of one. Cached for a minute (it reads the configuration file)."""
    now = time.time()
    if _self_cache['value'] is not None and now - _self_cache['at'] < 60:
        return _self_cache['value']
    from sajha.net import names
    out = []
    try:
        from sajha.core.net_extension import configured_nets
        entries = configured_nets() or [{'name': 'default'}]
    except Exception:
        entries = [{'name': 'default'}]
    host, port = _settings_host_port()
    for e in entries:
        net = str(e.get('name') or 'default')
        try:
            name, why = names.resolve_instance_name(str(e.get('instance_name') or ''),
                                                    str(e.get('advertise_address') or ''), host, port)
        except Exception as ex:                       # a malformed configured name
            name, why = None, str(ex)
        out.append({'net': net, 'instance': name or 'this server', 'name_problem': why or '',
                    'region': str(e.get('region') or ''),
                    'labels': {str(k): str(v) for k, v in (e.get('labels') or {}).items()}
                    if isinstance(e.get('labels'), dict) else {}})
    _self_cache.update(at=now, value=out)
    return out


def _service():
    from sajha.net.integration import get_service
    svc = get_service()
    return svc if svc is not None and svc.shared.enabled else None


def _rfc(ts) -> Optional[str]:
    if not ts:
        return None
    from sajha.net import crypto
    try:
        return crypto.rfc3339(float(ts))
    except Exception:
        return None


# ── access ──────────────────────────────────────────────────────────

def _may_use(auth, name: str) -> bool:
    """This server lets ``auth`` see and call tool ``name`` (the Tools page's rule)."""
    if auth is None:
        return False
    try:
        from sajha.auth.access import policy_for
        if not policy_for(auth).can_see(name):
            return False
    except Exception:
        pass
    try:
        return bool(auth.has_tool_access(name))
    except Exception:
        return True


def _registry():
    try:
        from sajha.app import tools_registry
        return tools_registry
    except Exception:
        return None


def _local_tools() -> List[Any]:
    reg = _registry()
    if reg is None:
        return []
    from sajha.net.integration.catalogs import NetProxyTool
    try:
        tools = list(reg.tools.values()) if hasattr(reg, 'tools') else []
    except Exception:
        tools = []
    return [t for t in tools if not isinstance(t, NetProxyTool) and getattr(t, 'enabled', True)]


# ── the Instances page ──────────────────────────────────────────────

def _rows(svc) -> List[Dict[str, Any]]:
    c = getattr(svc, 'catalogs', None) if svc is not None else None
    if c is None or c.router is None:
        return []
    try:
        return c.router.rows()
    except Exception as e:
        logger.debug(f'SAJHA Net console: rows: {e}')
        return []


def _self_entry(net: str, name: str, region: str = '', labels=None, url: str = '', networked: bool = False,
                auth=None, note: str = '', vendor: str = '') -> Dict[str, Any]:
    own = [t for t in _local_tools() if _may_use(auth, t.name)]
    return {'net': net, 'name': name, 'kind': 'sajha', 'region': region, 'labels': dict(labels or {}),
            'vendor': vendor,
            'state': 'alive', 'last_seen': _rfc(time.time()), 'url': url, 'self': True,
            'networked': networked, 'tools_total': len(_local_tools()), 'tools_usable': len(own), 'note': note}


def instances_view(auth=None) -> Dict[str, Any]:
    """Every participant per net, this server first."""
    svc = _service()
    nets: List[Dict[str, Any]] = []
    rows = _rows(svc)
    if svc is None:
        for s in self_identity():
            nets.append({'net': s['net'], 'instance': s['instance'], 'networked': False, 'single_member': True,
                         'state': 'off', 'instances': [_self_entry(s['net'], s['instance'], s['region'], s['labels'],
                                                                   auth=auth, note='SAJHA Net is off')]})
        return {'enabled': False, 'nets': nets}
    for net, rt in svc.runtimes.items():
        cfg = rt.cfg
        node = rt.node
        entry: Dict[str, Any] = {'net': net, 'instance': cfg.instance_name or 'this server',
                                 'networked': node is not None, 'error': rt.error}
        insts = [_self_entry(net, cfg.instance_name or 'this server', cfg.region, cfg.labels, cfg.base_url,
                             networked=node is not None, auth=auth, vendor=cfg.vendor,
                             note='' if node is not None else 'not networked yet')]
        members = []
        if node is not None:
            try:
                members = node.members()
            except Exception:
                members = []
        for m in members:
            rec = m.get('record') or {}
            mine = [r for r in rows if r['net'] == net and r['host_instance'] == m['name']]
            usable = [r for r in mine if r['state'] in LISTED and _may_use(auth, r['qualified_name'])]
            insts.append({'net': net, 'name': m['name'], 'kind': rec.get('kind') or 'sajha',
                          'region': rec.get('region') or '', 'labels': dict(rec.get('labels') or {}),
                          'state': m['state'], 'last_seen': _rfc(m.get('last_seen')), 'url': rec.get('url') or '',
                          'self': False, 'networked': True, 'tools_total': len(mine), 'tools_usable': len(usable),
                          'sponsor': rec.get('sponsor') or '', 'vendor': rec.get('vendor') or '',
                          'note': (f'sponsored by {rec.get("sponsor")}' if rec.get('kind') == 'sponsored' and
                                   rec.get('sponsor') else '')})
        st = node.status() if node is not None else {}
        entry['single_member'] = not members
        entry['state'] = ('name conflict' if node is not None and node.refused() else
                          'joined' if node is not None and node.joined() else
                          'not networked' if node is None else 'not joined')
        entry['founder_alone'] = bool(st.get('founder_alone')) and not members
        entry['instances'] = insts
        nets.append(entry)
    return {'enabled': True, 'nets': nets}


def _schema_fields(schema: Any) -> List[Dict[str, str]]:
    if not isinstance(schema, dict):
        return []
    req = set(schema.get('required') or [])
    out = []
    for k, v in (schema.get('properties') or {}).items():
        v = v if isinstance(v, dict) else {}
        t = v.get('type')
        out.append({'name': str(k), 'type': '|'.join(t) if isinstance(t, list) else str(t or 'any'),
                    'required': k in req, 'description': str(v.get('description') or '')[:300]})
    return out


def instance_view(net: str, instance: str, auth=None) -> Optional[Dict[str, Any]]:
    """One participant and the tools it offers this user, or None when it is not in ``net``."""
    view = instances_view(auth)
    n = next((x for x in view['nets'] if x['net'] == net), None)
    if n is None:
        return None
    inst = next((i for i in n['instances'] if i['name'] == instance), None)
    if inst is None:
        return None
    tools: List[Dict[str, Any]] = []
    reg = _registry()
    if inst['self']:
        for t in sorted(_local_tools(), key=lambda t: t.name):
            if not _may_use(auth, t.name):
                continue
            try:
                d = t.to_mcp_format()
            except Exception:
                continue
            tools.append({'name': t.name, 'qualified_name': '', 'alias': '', 'description': d.get('description') or '',
                          'inputs': _schema_fields(d.get('inputSchema')), 'outputs': _schema_fields(d.get('outputSchema')),
                          'state': 'active', 'latency_ms': None, 'try_it': t.name})
    else:
        svc = _service()
        c = getattr(svc, 'catalogs', None) if svc is not None else None
        aliases = {}
        if c is not None and c.router is not None:
            try:
                aliases = c.router.aliases()
            except Exception:
                aliases = {}
        for r in _rows(svc):
            if r['net'] != net or r['host_instance'] != instance:
                continue
            if r['state'] not in LISTED or not _may_use(auth, r['qualified_name']):
                continue
            d = (r.get('entry') or {}).get('definition') or {}
            lat = None
            try:
                lat = c.router.latency_p50(net, instance)
            except Exception:
                pass
            alias = next((p for p, qs in aliases.items() if r['qualified_name'] in qs), '')
            registered = reg is not None and reg.get_tool(r['qualified_name']) is not None
            tools.append({'name': r['host_tool'], 'qualified_name': r['qualified_name'], 'alias': alias or '',
                          'description': d.get('description') or '', 'inputs': _schema_fields(d.get('inputSchema')),
                          'outputs': _schema_fields(d.get('outputSchema')), 'state': r['state'],
                          'version': r.get('version') or '',
                          'vendor': str(((r.get('entry') or {}).get('meta') or {}).get('vendor') or ''),
                          'external': bool(((r.get('entry') or {}).get('meta') or {}).get('external')),
                          'latency_ms': int(lat) if lat is not None else None,
                          'try_it': r['qualified_name'] if registered and r['state'] == 'active' else ''})
        tools.sort(key=lambda t: t['name'])
    return {'net': net, 'instance': inst, 'tools': tools, 'enabled': view['enabled']}


# ── the navbar badge ────────────────────────────────────────────────

def badge() -> Dict[str, Any]:
    """``{label, title, health, nets: [{net, instance, health}]}``; health is ``ok``, ``warn``, ``bad``
    or ``solo`` (a net of one: nothing to be connected to)."""
    svc = _service()
    nets: List[Dict[str, Any]] = []
    if svc is None:
        nets = [{'net': s['net'], 'instance': s['instance'], 'health': 'solo', 'words': 'a net of one (SAJHA Net off)'}
                for s in self_identity()]
    else:
        for net, rt in svc.runtimes.items():
            node = rt.node
            name = rt.cfg.instance_name or 'this server'
            if node is None:
                h, w = ('solo', 'a net of one, not networked') if not rt.cfg.seeds else ('bad', 'not joined')
            else:
                try:
                    members = node.members()
                    if node.refused():
                        h, w = 'bad', 'name conflict'
                    elif not node.joined():
                        h, w = 'bad', 'not joined'
                    elif not members:
                        h, w = 'solo', 'a net of one'
                    elif any(m['state'] in ('suspect', 'dead') for m in members):
                        h, w = 'warn', 'joined; some members suspect or dead'
                    else:
                        h, w = 'ok', f'joined; {len(members) + 1} instances'
                except Exception:
                    h, w = 'warn', 'state unknown'
            nets.append({'net': net, 'instance': name, 'health': h, 'words': w})
    if not nets:
        return {}
    rank = {'bad': 3, 'warn': 2, 'ok': 1, 'solo': 0}
    worst = max(nets, key=lambda n: rank.get(n['health'], 0))['health']
    if len(nets) == 1:
        label = f'Net · {nets[0]["instance"]}'
    else:
        label = f'Net · {nets[0]["instance"]} +{len(nets) - 1}'     # the first configured net, plus a count
    title = '; '.join(f'{n["net"]}: {n["instance"]} ({n["words"]})' for n in nets)
    return {'label': label, 'title': title, 'health': worst, 'nets': nets, 'name': nets[0]['instance'],
            'more': len(nets) - 1}


def badge_safe() -> Dict[str, Any]:
    try:
        return badge()
    except Exception as e:
        logger.debug(f'SAJHA Net badge: {e}')
        return {}
