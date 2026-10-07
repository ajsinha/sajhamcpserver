"""
SAJHA Net catalogs and routing inside SAJHA (design §7, §8, §9, §15, §17.2, §17.4; protocol §10, §15).

* :class:`NativeCatalog` (catalog source ``native``): this server's own registry tools, never proxies
  or federated tools (an instance exports only its own tools unless re-export is built, design §14),
  with each tool's configured ``version``.
* :class:`NetProxyTool`: a remote tool in the registry, under its qualified name
  (``<net>__<instance>__<tool>``) and, while a bare alias is offered, under its plain name too. Calls
  go through ``execute_with_tracking`` like every tool (access, policy, argument validation,
  metrics), then :meth:`sajha.net.routing.Router.call`; the host's result is returned as is
  (``passthrough_result``), a refusal as an ``isError`` result with ``_meta["io.sajha/net"].refusal``.
* :class:`NetCatalogs`, one per :class:`~sajha.net.integration.SajhaNetService`: a
  :class:`~sajha.net.catalog.CatalogBook` and a :class:`~sajha.net.routing.HostServer` per net, one
  :class:`~sajha.net.routing.Router` over the nets in configured order, the proxies in this worker's
  registry kept equal to the host and tool table (every worker syncs from the state store), the
  local quarantine of tools this server exports, notices, audit records and metrics.

Configuration (design §19): ``sajhanet.preferences``, ``max_fallbacks``, ``bare_aliases``,
``default_trust``, ``refresh_interval_seconds``, ``default_timeout_seconds``, ``max_hops``,
``reexport``, ``limits.*``, ``peer.*`` and ``plugins.routing``; ``default_trust``, ``reexport``,
``max_hops`` and ``refresh_interval_seconds`` may also be set in a net entry. Trust levels and
approvals set at runtime live in the storage backend (``<data_dir>/<net>/trust.json``).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID, names, plugins
from sajha.net.catalog import TRUST_LEVELS, CatalogBook, Limits
from sajha.net.plugins import CatalogSource
from sajha.net.routing import CallContext, HostRefusal, HostServer, PeerSettings, Router
from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)

NOTICE_LINK = '/help/guides/SAJHA%20Net.md'
LISTED_STATES = ('active', 'unavailable')


# ── settings ────────────────────────────────────────────────────────

def _g(key: str, default: Any) -> Any:
    from sajha.net.integration.config import _g as g
    return g(key, default)


def _raw() -> Dict[str, Any]:
    from sajha.net.integration.config import _raw as r
    return r()


def _num(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class CatalogSettings:
    preferences: Dict[str, List[str]] = field(default_factory=dict)
    max_fallbacks: int = 3
    bare_aliases: str = 'on'
    default_trust: str = 'auto'
    refresh_interval_seconds: float = 300
    default_timeout_seconds: float = 30
    max_hops: int = 1
    reexport: bool = False
    routing: str = 'local_first'
    limits: Limits = field(default_factory=Limits)
    peer: PeerSettings = field(default_factory=PeerSettings)
    host_calls_per_minute: int = 600
    anonymous_may_call_remote: bool = False
    per_net: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def for_net(self, net: str, key: str) -> Any:
        v = (self.per_net.get(net) or {}).get(key)
        return getattr(self, key) if v is None else v


def load_settings() -> CatalogSettings:
    from sajha.core.config import parse_bool
    from sajha.core.net_extension import configured_nets
    raw = _raw()
    s = CatalogSettings()
    prefs = raw.get('preferences')
    if isinstance(prefs, dict):
        s.preferences = {str(k): [str(x) for x in (v or [])] for k, v in prefs.items() if isinstance(v, list)}
    s.max_fallbacks = max(0, int(_num(_g('max_fallbacks', 3), 3)))
    ba = _g('bare_aliases', 'on')
    ba = {True: 'on', False: 'off'}.get(ba, ba) if isinstance(ba, bool) else str(ba).lower()
    s.bare_aliases = {'true': 'on', 'false': 'off', 'yes': 'on', 'no': 'off'}.get(ba, ba)
    if s.bare_aliases not in ('on', 'preferences_only', 'off'):
        s.bare_aliases = 'on'
    t = str(_g('default_trust', 'auto')).lower()
    s.default_trust = t if t in TRUST_LEVELS else 'auto'
    s.refresh_interval_seconds = max(5.0, _num(_g('refresh_interval_seconds', 300), 300))
    s.default_timeout_seconds = max(1.0, _num(_g('default_timeout_seconds', 30), 30))
    s.max_hops = max(1, min(8, int(_num(_g('max_hops', 1), 1))))
    s.reexport = parse_bool(_g('reexport', 'false'), False)
    s.routing = str(_g('plugins.routing', 'local_first'))
    s.limits = Limits(max_tools_per_peer=int(_num(_g('limits.max_tools_per_peer', 2000), 2000)),
                      max_catalog_bytes=int(_num(_g('limits.max_catalog_bytes', 5242880), 5242880)),
                      max_description_chars=int(_num(_g('limits.max_description_chars', 1024), 1024)))
    s.peer = PeerSettings(timeout_seconds=s.default_timeout_seconds,
                          breaker_threshold=int(_num(_g('peer.breaker_threshold', 5), 5)),
                          breaker_reset_seconds=_num(_g('peer.breaker_reset_seconds', 30), 30),
                          calls_per_minute=int(_num(_g('peer.calls_per_minute', 600), 600)))
    s.host_calls_per_minute = int(_num(_g('peer.inbound_calls_per_minute', 600), 600))
    s.anonymous_may_call_remote = parse_bool(_g('anonymous_may_call_remote', 'false'), False)
    for entry in configured_nets():
        over = {}
        for k in ('default_trust', 'reexport', 'max_hops', 'refresh_interval_seconds'):
            if entry.get(k) is not None:
                over[k] = entry[k]
        if over:
            s.per_net[str(entry.get('name') or 'default')] = over
    return s


# ── the catalog source ──────────────────────────────────────────────

def _registry():
    from sajha.tools.tools_registry import get_tools_registry
    return get_tools_registry()


def _own_tools(reg) -> List[BaseMCPTool]:
    from sajha.federation.tool import FederatedTool
    with reg._tools_lock:
        items = list(reg.tools.values())
    return [t for t in items if t.enabled and not isinstance(t, (NetProxyTool, FederatedTool))]


@plugins.register('catalog_source')
class NativeCatalog(CatalogSource):
    """This server's own registry tools as MCP Tool objects, with their versions."""
    name = 'native'

    def __init__(self, registry=None):
        self._registry = registry

    def tools(self, net, peer=None):
        reg = self._registry or _registry()
        if reg is None:
            return []
        out = []
        for tool in _own_tools(reg):
            try:
                d = tool.to_mcp_format()
            except Exception as e:
                logger.debug(f'SAJHA Net catalog: {getattr(tool, "name", "?")}: {e}')
                continue
            cfg = getattr(tool, 'config', None) or {}
            meta_cat = str(((cfg.get('metadata') or {}).get('category')) or '')
            extra: Dict[str, Any] = {'version': str(getattr(tool, 'version', '') or cfg.get('version') or '')}
            if meta_cat == 'llm' or cfg.get('llm') or cfg.get('type') == 'llm':
                extra['llm_tool'] = True
            d['_net'] = {k: v for k, v in extra.items() if v not in ('', None)}
            out.append(d)
        return out


# ── proxy tools ─────────────────────────────────────────────────────

def _caller_user(net_hint: str = '') -> Dict[str, Any]:
    from sajha.observability.caller import current
    c = current()
    return {'user_id': c.user_id, 'roles': list(c.roles), 'is_admin': c.is_admin, 'auth_type': c.auth_type,
            'api_key': c.api_key, 'authenticated': c.user_id not in ('', 'anonymous'), 'net': net_hint}


class NetProxyTool(BaseMCPTool):
    """A remote tool in this server's registry (see the module docstring)."""
    passthrough_result = True

    def __init__(self, catalogs: 'NetCatalogs', name: str, definition: Dict[str, Any], meta: Dict[str, Any],
                 fingerprint: str, alias: bool = False):
        from sajha.federation.security import correct_annotations
        cfg = {'name': name, 'description': definition.get('description') or '',
               'inputSchema': definition.get('inputSchema') or {'type': 'object', 'properties': {}},
               'outputSchema': definition.get('outputSchema') or {},
               'metadata': {'category': 'sajhanet', 'tags': ['sajhanet', meta.get('net', ''), meta.get('instance', '')]},
               'version': meta.get('version') or '1.0.0', 'enabled': True,
               'annotations': correct_annotations(definition.get('annotations'))}
        if definition.get('title'):
            cfg['title'] = definition['title']
        super().__init__(cfg)
        self.catalogs = catalogs
        self.definition = definition
        self.meta = meta
        self.fingerprint = fingerprint
        self.alias = alias

    def get_input_schema(self) -> Dict:
        return self._input_schema or {'type': 'object', 'properties': {}}

    def get_output_schema(self) -> Dict:
        return self._output_schema or {}

    def get_description(self) -> str:
        return self.description

    def execute(self, arguments: Dict[str, Any]) -> Any:
        return self.catalogs.call(self.name, dict(arguments or {}))

    def to_mcp_format(self) -> Dict:
        d = self.definition
        tool = {'name': self.name, 'description': self.description, 'inputSchema': self.input_schema}
        for key in ('title', 'outputSchema'):
            if d.get(key):
                tool[key] = copy.deepcopy(d[key])
        tool['annotations'] = copy.deepcopy(self.config.get('annotations') or {'openWorldHint': True})
        meta = dict(d.get('_meta') or {})
        meta[EXTENSION_ID] = copy.deepcopy(self.meta)
        tool['_meta'] = meta
        return tool

    def format_mcp_result(self, result: Any, advertise_output_schema: bool = True) -> Dict[str, Any]:
        if isinstance(result, dict) and isinstance(result.get('content'), list):
            out = {'content': result['content']}
            if advertise_output_schema and 'structuredContent' in result:
                out['structuredContent'] = result['structuredContent']
            if result.get('isError'):
                out['isError'] = True
            if isinstance(result.get('_meta'), dict):
                out['_meta'] = result['_meta']
            return out
        return {'content': [{'type': 'text', 'text': str(result)}]}


class LocalQuarantined(RuntimeError):
    """A local tool this server exports into a net where its name is quarantined (§10.7)."""

    def __init__(self, name: str, report: Dict[str, Any]):
        super().__init__(f'{name} is quarantined in {report.get("net")}: its hosts disagree on its contract. '
                         + (report.get('text') or '').splitlines()[0])
        self.report = report


# ── the service part ────────────────────────────────────────────────

class NetCatalogs:
    def __init__(self, svc, settings: Optional[CatalogSettings] = None, registry=None):
        self.svc = svc
        self.settings = settings or load_settings()
        self._registry = registry
        self.books: Dict[str, CatalogBook] = {}
        self.hosts: Dict[str, HostServer] = {}
        self.router: Optional[Router] = None
        self._proxies: Dict[str, NetProxyTool] = {}
        self._lock = threading.RLock()
        self._table_stamp: Any = None
        self.counters: Dict[Tuple[str, ...], int] = {}

    # ── wiring ─────────────────────────────────────────────────────

    @property
    def registry(self):
        return self._registry or _registry()

    def _authz_parts(self):
        a = getattr(self.svc, 'authz', None)
        identity = getattr(a, 'identity', None) if a is not None else None
        rules = getattr(a, 'rules', None) if a is not None else None
        return identity or plugins.NoIdentity(), rules or plugins.AllowAll()

    def _trust_doc(self, net: str) -> Dict[str, Any]:
        try:
            r, _ = self.svc._doc_io(f'{self.svc.shared.data_dir}/{net}/trust.json')
            return r() or {}
        except Exception:
            return {}

    def _save_trust_doc(self, net: str, doc: Dict[str, Any]) -> None:
        _, w = self.svc._doc_io(f'{self.svc.shared.data_dir}/{net}/trust.json')
        w(doc)

    def attach(self, cfg, node) -> Optional[CatalogBook]:
        """Install the catalog book and the MCP host endpoint on one net's node (before it starts gossiping)."""
        if node is None:
            return None
        net = cfg.name
        identity, rules = self._authz_parts()
        from sajha.federation.security import schema_problem, screen_text
        s = self.settings
        book = CatalogBook(node, NativeCatalog(self._registry), rules=rules,
                           trust_of=lambda peer, net=net: self.trust_of(net, peer),
                           approvals=lambda peer, net=net: self.approvals(net, peer),
                           screen_text=screen_text, schema_problem=schema_problem, limits=s.limits,
                           refresh_interval=float(s.for_net(net, 'refresh_interval_seconds')),
                           default_trust=str(s.for_net(net, 'default_trust')),
                           reexport=bool(s.for_net(net, 'reexport')),
                           run_ttl=max(60.0, self.svc.shared.agent_lease_seconds * 4)).attach()
        node.observers.append(lambda kind, data, net=net: self._on_event(net, kind, data))
        book.start()
        self.books[net] = book
        host = HostServer(book, execute=self._execute, identity=identity, rules=rules,
                          max_hops=int(s.for_net(net, 'max_hops')),
                          own_identities=lambda: [f'{n}/{b.node.name}' for n, b in self.books.items()],
                          other=lambda msg, v, net=net: self._other(net, msg, v),
                          calls_per_minute=s.host_calls_per_minute, audit=self._audit).attach()
        self.hosts[net] = host
        self._build_router()
        return book

    def detach(self, net: str) -> None:
        self.books.pop(net, None)
        self.hosts.pop(net, None)
        self._build_router()
        self.sync_registry()

    def _build_router(self) -> None:
        order = [n for n in self.svc.runtimes if n in self.books]
        identity, rules = self._authz_parts()
        try:
            routing = plugins.create('routing', self.settings.routing)
        except Exception as e:
            logger.warning(f'sajhanet.plugins.routing: {e}; using local_first')
            routing = plugins.create('routing', 'local_first')
        self.router = Router([self.books[n] for n in order], local_tools=self._local_names,
                             preferences=self.settings.preferences, routing=routing,
                             bare_aliases=self.settings.bare_aliases, max_fallbacks=self.settings.max_fallbacks,
                             default_timeout=self.settings.default_timeout_seconds, identity=identity, rules=rules,
                             peer=self.settings.peer, clock=self.svc.clock, audit=self._audit,
                             screen_result=_screen_result, max_hops=self.settings.max_hops)

    def _local_names(self) -> List[str]:
        reg = self.registry
        return [t.name for t in _own_tools(reg)] if reg is not None else []

    # ── trust (design §7.3) ────────────────────────────────────────

    def trust_of(self, net: str, peer: str) -> Tuple[str, List[str]]:
        p = (self._trust_doc(net).get('peers') or {}).get(peer) or {}
        level = p.get('trust') if p.get('trust') in TRUST_LEVELS else str(self.settings.for_net(net, 'default_trust'))
        return level, list(p.get('pinned') or [])

    def approvals(self, net: str, peer: str) -> Dict[str, Dict[str, Any]]:
        return dict(((self._trust_doc(net).get('peers') or {}).get(peer) or {}).get('approved') or {})

    def set_trust(self, net: str, peer: str, level: str, pinned: Optional[List[str]] = None, by: str = '') -> Dict[str, Any]:
        from sajha.net.integration import ServiceError, _audit
        if level not in TRUST_LEVELS:
            raise ServiceError(400, f'trust is one of {", ".join(TRUST_LEVELS)}')
        book = self._book(net)
        doc = self._trust_doc(net)
        p = (doc.setdefault('peers', {})).setdefault(peer, {})
        p['trust'] = level
        if pinned is not None:
            p['pinned'] = sorted({str(x) for x in pinned})
        self._save_trust_doc(net, doc)
        _audit('trust_changed', by, {'net': net, 'peer': peer, 'trust': level, 'pinned': p.get('pinned')})
        self._repull(book, peer)
        return {'net': net, 'peer': peer, 'trust': level, 'pinned': p.get('pinned', [])}

    def approve(self, net: str, peer: str, tool: str, approve: bool = True, by: str = '') -> Dict[str, Any]:
        """Approve (or withdraw approval of) a peer's tool under ``review`` trust, at its current contract."""
        from sajha.net.integration import ServiceError, _audit
        book = self._book(net)
        held = book._held(peer)
        doc = self._trust_doc(net)
        p = (doc.setdefault('peers', {})).setdefault(peer, {})
        appr = p.setdefault('approved', {})
        if approve:
            raw = self._fresh_entry(book, peer, tool)
            if raw is None:
                raise ServiceError(404, f'{peer} does not offer {tool} in {net}')
            appr[tool] = {'contract_hash': raw['contract_hash'], 'description_hash': raw['description_hash'],
                          'entry': dict(raw, state='active'), 'by': by}
        else:
            appr.pop(tool, None)
        self._save_trust_doc(net, doc)
        _audit('tool_approved' if approve else 'tool_approval_withdrawn', by, {'net': net, 'peer': peer, 'tool': tool})
        self._repull(book, peer)
        return {'net': net, 'peer': peer, 'tool': tool, 'approved': approve, 'held_tools': len(held.get('tools') or [])}

    def _fresh_entry(self, book: CatalogBook, peer: str, tool: str) -> Optional[Dict[str, Any]]:
        m = book.node.member(peer)
        if m is None:
            return None
        x = book.node.request(m['record']['url'], '/sajhanet/v1/catalog', {}, peer)
        for raw in (x.body or {}).get('tools') or []:
            if raw.get('name') == tool:
                return book._accept_one(peer, raw, [])
        return None

    def _repull(self, book: CatalogBook, peer: str) -> None:
        m = book.node.member(peer)
        if m is not None and m['state'] == 'alive':
            book.kv.update('cat:' + peer, lambda cur: dict(cur or {}, hash=None) if cur else None)
            try:
                book.pull(m, 'trust')
            except Exception as e:
                logger.debug(f'SAJHA Net re-pull of {peer}: {e}')
        book.evaluate()
        self.sync_registry()

    def _book(self, net: str) -> CatalogBook:
        from sajha.net.integration import ServiceError
        b = self.books.get(net)
        if b is None:
            raise ServiceError(404, f'net {net!r} is not running on this server')
        return b

    # ── the registry (every worker) ────────────────────────────────

    def sync_registry(self) -> bool:
        """Make this worker's proxies equal the host and tool table. True when something changed."""
        reg = self.registry
        if reg is None or self.router is None:
            return False
        rows = self.router.rows()
        aliases = self.router.aliases()
        by_q = {r['qualified_name']: r for r in rows}
        desired: Dict[str, Tuple[Dict[str, Any], Dict[str, Any], bool]] = {}
        alias_of = {qs[0]: plain for plain, qs in aliases.items() if qs}
        for r in rows:
            if r['state'] not in LISTED_STATES:
                continue
            meta = self._meta(r, alias=next((p for p, qs in aliases.items() if r['qualified_name'] in qs), None))
            desired[r['qualified_name']] = (r['entry']['definition'], meta, False)
        for plain, qs in aliases.items():
            first = by_q.get(qs[0])
            if first is None:
                continue
            meta = self._meta(first, alias=plain)
            meta['resolution'] = qs
            desired[plain] = (first['entry']['definition'], meta, True)
        changed = False
        from sajha.tools.tools_registry import registry_bulk
        with self._lock, registry_bulk(reg):
            for name in list(self._proxies):
                want = desired.get(name)
                cur = self._proxies[name]
                if want is None or _fp(want) != cur.fingerprint:
                    self._proxies.pop(name)
                    if reg.get_tool(name) is cur:
                        reg.unregister_tool(name)
                    changed = True
            for name, want in desired.items():
                if name in self._proxies:
                    continue
                existing = reg.get_tool(name)
                if existing is not None and not isinstance(existing, NetProxyTool):
                    continue                                  # a local tool keeps its name (design §8.2)
                tool = NetProxyTool(self, name, want[0], want[1], _fp(want), alias=want[2])
                self._proxies[name] = tool
                reg.register_tool(tool)
                changed = True
        return changed

    def _meta(self, r: Dict[str, Any], alias: Optional[str]) -> Dict[str, Any]:
        e = r['entry']
        m = {k: v for k, v in (e.get('meta') or {}).items() if k != 'origin' or v}
        m.update(net=r['net'], instance=r['host_instance'], locality='remote', qualified_name=r['qualified_name'],
                 host_tool=r['host_tool'])
        if alias:
            m['alias'] = alias
        if r['state'] != 'active':
            m['state'] = r['state']
        lat = self.router.latency_p50(r['net'], r['host_instance']) if self.router else None
        if lat is not None:
            m['latency_ms_p50'] = int(lat)
        return m

    def reregister_after_reload(self) -> None:
        reg = self.registry
        with self._lock:
            for name, tool in list(self._proxies.items()):
                if reg.get_tool(name) is None:
                    reg.register_tool(tool)

    def clear_registry(self) -> None:
        reg = self.registry
        with self._lock:
            for name, tool in list(self._proxies.items()):
                if reg is not None and reg.get_tool(name) is tool:
                    reg.unregister_tool(name)
            self._proxies.clear()

    def stamp(self) -> Any:
        """What the table depends on, cheaply (the worker loop re-syncs when it changes)."""
        out = []
        for net, b in self.books.items():
            out.append((net, tuple(sorted((k, (v or {}).get('hash'), (v or {}).get('run'), (v or {}).get('incarnation'))
                                          for k, v in b.kv.scan('cat:'))),
                        tuple(sorted((m['name'], m['state']) for m in b.node.members())),
                        json.dumps(sorted(b.quarantined()), default=str), b.kv.get('run')))
        return tuple(out)

    def maybe_sync(self) -> None:
        st = self.stamp()
        if st != self._table_stamp:
            self._table_stamp = st
            self.sync_registry()

    # ── calls ──────────────────────────────────────────────────────

    def call(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.observability import tracing
        user = _caller_user()
        if not user['authenticated'] and not self.settings.anonymous_may_call_remote and \
                getattr(self.svc, 'authz', None) is None:
            res = self.router.resolve(name)
            return self.router._home_result(res, -32013, 'anonymous', 'the call needs a signed-in user', '')
        tp = None
        try:
            tp = tracing.current_traceparent()
        except Exception:
            tp = None
        return self.router.call(name, arguments, user=user, traceparent=tp)

    def local_quarantine(self, name: str) -> Optional[Dict[str, Any]]:
        if self.router is None or not self.books:
            return None
        try:
            return self.router.local_quarantine(name)
        except Exception as e:
            logger.debug(f'SAJHA Net quarantine check {name}: {e}')
            return None

    def _execute(self, ctx: CallContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Steps 10 and 11 of §15.4: this server's own access, policy and approvals; then the tool."""
        reg = self.registry
        tool = reg.get_tool(ctx.tool) if reg is not None else None
        if tool is None or isinstance(tool, NetProxyTool):
            raise HostRefusal('export')
        from sajha.observability.caller import Caller, reset, set_caller
        user = ctx.user or {}
        roles = tuple(user.get('roles') or ())
        uid = str(user.get('user_id') or user.get('name') or f'sajhanet:{ctx.net}/{ctx.peer}')
        access = None
        if ctx.user is not None:
            try:
                from sajha.auth import AuthContext
                from sajha.auth.access import policy_for
                auth = AuthContext(authenticated=True, user_id=uid, user_name=str(user.get('user_name_local') or uid),
                                   roles=list(roles), auth_type='sajhanet', is_admin='admin' in roles,
                                   api_key_mode=user.get('tool_access_mode') or None,
                                   api_key_tools=json.dumps(user.get('tool_access_list') or []))
                access = policy_for(auth).can_execute
            except Exception as e:
                logger.warning(f'SAJHA Net: access policy for {uid}: {e}')
                raise HostRefusal('access')
            if not access(ctx.tool):
                raise HostRefusal('access')
        token = set_caller(Caller(uid, '', roles, 'sajhanet', access, 'admin' in roles))
        try:
            from sajha.core.mcp_mrtr import InputRequired
            from sajha.policy.errors import PolicyError
            from sajha.tools.base_mcp_tool import ToolArgumentError
            try:
                result = tool.execute_with_tracking(arguments)
            except PolicyError as e:
                raise HostRefusal('approval_required' if e.kind == 'approval_required' else 'policy')
            except PermissionError:
                raise HostRefusal('access')
            except ToolArgumentError as e:
                return {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
            except InputRequired:
                return {'content': [{'type': 'text', 'text': f'{ctx.tool} needs input that a forwarded call '
                                                             f'cannot relay yet'}], 'isError': True}
            except Exception as e:
                return {'content': [{'type': 'text', 'text': f'Tool execution failed: {e}'}], 'isError': True}
            return _format_result(tool, result)
        finally:
            reset(token)

    def _other(self, net: str, msg: Dict[str, Any], v) -> Dict[str, Any]:
        """``server/discover``, ``initialize``, ``ping`` from a participant: the extension object of that
        net only (NET-04)."""
        from sajha.core import net_extension
        rid = msg.get('id')
        method = msg.get('method')
        with net_extension.signed_for(net):
            if method == 'ping':
                return {'jsonrpc': '2.0', 'id': rid, 'result': {}}
            if method in ('server/discover', 'initialize'):
                try:
                    from sajha.app import mcp_handler
                    if mcp_handler is not None and method == 'initialize':
                        return {'jsonrpc': '2.0', 'id': rid, 'result': mcp_handler.server_info}
                except Exception as e:
                    logger.debug(f'SAJHA Net initialize: {e}')
                ext = net_extension.extension_object(net) or {}
                return {'jsonrpc': '2.0', 'id': rid, 'result': {
                    'supportedVersions': ['2026-07-28', '2025-11-25'],
                    'capabilities': {'extensions': {EXTENSION_ID: ext}, 'tools': {}}}}
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': f'{method} is not served to net peers'}}

    # ── operators: notices, audit, metrics ─────────────────────────

    def _audit(self, what: str, details: Dict[str, Any]) -> None:
        if what == 'net.call_attempt':
            key = ('fallback_attempts',) if int(details.get('attempt') or 1) > 1 else ('first_attempts',)
            self.counters[key] = self.counters.get(key, 0) + 1
        try:
            from sajha.net.integration.authz import linked_audit
            linked_audit(what, details)
        except ImportError:
            from sajha.net.integration import _audit
            _audit(what, details=details)

    def _on_event(self, net: str, kind: str, data: Dict[str, Any]) -> None:
        from sajha.net.integration import _audit, _clear, _notice
        if kind == 'tool_quarantined':
            r = data.get('report') or {}
            tool = data.get('tool')
            _notice(f'sajhanet.conflict:{net}:{tool}', 'error', f'Tool {tool} quarantined in {net}',
                    r.get('text') or '', ttl=0)
            _audit('tool_quarantined', details={'net': net, 'tool': tool, 'offers': r.get('offers'),
                                                'differing': r.get('differing'), 'agreeing': r.get('agreeing'),
                                                'differences': r.get('differences'), 'reported_by': r.get('reported_by')})
            self._alert(net, tool, r)
        elif kind == 'tool_reactivated':
            tool = data.get('tool')
            _clear(f'sajhanet.conflict:{net}:{tool}')
            _notice(f'sajhanet.reactivated:{net}:{tool}', 'info', f'Tool {tool} active again in {net}',
                    data.get('text') or '', ttl=60)
            _audit('tool_reactivated', details={'net': net, 'tool': tool, 'change': data.get('change')})
        elif kind == 'catalog_flag' and data.get('flag') not in ('pull_failed',):
            _notice(f'sajhanet.catalog:{net}:{data.get("peer")}', 'warning',
                    f'Catalog of {data.get("peer")} flagged in {net}', data.get('detail') or data.get('flag') or '',
                    ttl=60)
        elif kind in ('tool_changed', 'tool_offered', 'tool_withdrawn'):
            _audit(f'remote_{kind}', details={'net': net, **{k: v for k, v in data.items() if k not in ('net',)}})

    def _alert(self, net: str, tool: str, report: Dict[str, Any]) -> None:
        try:
            from sajha.observability import alerts
            fire = getattr(alerts, 'fire', None) or getattr(alerts, 'raise_alert', None)
            if callable(fire):
                fire('sajha_net_contract_conflict', {'net': net, 'tool': tool,
                                                     'differing': ','.join(report.get('differing') or [])})
        except Exception:
            pass

    def metrics(self) -> List[tuple]:
        conflicts, remote, pulls, calls, fallbacks = [], [], [], [], []
        for net, b in self.books.items():
            conflicts.append(({'net': net}, float(len(b.quarantined()))))
            states: Dict[str, int] = {}
            for r in b.rows():
                states[r['state']] = states.get(r['state'], 0) + 1
            for st, n in states.items():
                remote.append(({'net': net, 'state': st}, float(n)))
            pulls.append(({'net': net}, float(b.counters.get('pulls', 0))))
        if self.router is not None:
            for key, n in sorted(self.router.counters.items()):
                if key[0] == 'calls':
                    calls.append(({'outcome': key[1]}, float(n)))
                elif key[0] == 'fallbacks':
                    fallbacks.append(({'outcome': key[1]}, float(n)))
        return [
            ('sajha_net_contract_conflicts', 'gauge', 'Tool names quarantined for a contract conflict, by net.',
             [('sajha_net_contract_conflicts', l, v) for l, v in conflicts]),
            ('sajha_net_remote_tools', 'gauge', 'Remote tools in the host and tool table, by net and state.',
             [('sajha_net_remote_tools', l, v) for l, v in remote]),
            ('sajha_net_catalog_pulls_total', 'counter', 'Catalog pulls from peers, by net.',
             [('sajha_net_catalog_pulls_total', l, v) for l, v in pulls]),
            ('sajha_net_remote_calls_total', 'counter', 'Calls to remote tools at this home, by outcome.',
             [('sajha_net_remote_calls_total', l, v) for l, v in calls]),
            ('sajha_net_fallbacks_total', 'counter', 'Fallback attempts to another host, by outcome.',
             [('sajha_net_fallbacks_total', l, v) for l, v in fallbacks]),
        ]

    # ── views (admin API) ──────────────────────────────────────────

    def table(self, net: Optional[str] = None) -> Dict[str, Any]:
        """The host and tool table with each plain name's resolution order (design §8.4)."""
        rows = []
        router = self.router
        if router is None:
            return {'rows': [], 'resolution': {}, 'aliases': {}}
        aliases = router.aliases()
        for r in router.rows():
            if net and r['net'] != net:
                continue
            rows.append({k: v for k, v in r.items() if k not in ('entry', 'member')})
        resolution = {}
        local = set(self._local_names())
        for part in sorted({r['part'] for r in rows}):
            res = router.resolve(part)
            resolution[part] = res.public()
            if part in local:
                resolution[part]['local_tool'] = True
        for r in rows:
            r['alias'] = next((p for p, qs in aliases.items() if r['qualified_name'] in qs), None)
            res = resolution.get(r['part']) or {}
            place = next((c for c in res.get('order', []) if c.get('qualified_name') == r['qualified_name']), None)
            skip = next((c for c in res.get('skipped', []) if c.get('qualified_name') == r['qualified_name']), None)
            if place:
                r['resolution'] = f'{place["place"] + (1 if res.get("kind") == "local" else 0)}: {place["reason"]}'
            elif res.get('kind') == 'local':
                r['resolution'] = 'local tool wins the plain name; qualified name only'
            elif skip:
                r['resolution'] = f'not eligible: {skip.get("not_eligible")}'
            else:
                r['resolution'] = ''
        return {'rows': rows, 'resolution': resolution, 'aliases': aliases,
                'preferences': self.settings.preferences, 'max_fallbacks': self.settings.max_fallbacks,
                'bare_aliases': self.settings.bare_aliases}

    def conflicts(self, net: Optional[str] = None) -> Dict[str, Any]:
        out = {}
        for n, b in self.books.items():
            if net and n != net:
                continue
            out[n] = {'quarantined': b.quarantined(), 'document': b.kv.get('conf_doc'),
                      'warnings': self._description_warnings(b)}
        return {'nets': out}

    def _description_warnings(self, b: CatalogBook) -> List[Dict[str, Any]]:
        """Hosts offering one contract with different descriptions or titles (a warning, never a conflict)."""
        out = []
        groups: Dict[Tuple[str, str], set] = {}
        for r in b.rows():
            groups.setdefault((r['part'], r['contract_hash']), set()).add((r['host_instance'], r['description_hash']))
        for (part, _ch), hosts in groups.items():
            if len({d for _h, d in hosts}) > 1:
                out.append({'tool': part, 'hosts': sorted(h for h, _d in hosts)})
        return out

    def status(self) -> Dict[str, Any]:
        return {n: b.status() for n, b in self.books.items()}


def _fp(want: Tuple[Dict[str, Any], Dict[str, Any], bool]) -> str:
    d, m, alias = want
    m = {k: v for k, v in m.items() if k != 'latency_ms_p50'}
    return json.dumps([d, m, alias], sort_keys=True, default=str)


def _screen_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Results from a host are untrusted text (design §9 step 15): text blocks screened and capped."""
    from sajha.federation.security import screen_text
    out = dict(result)
    blocks = []
    for b in result.get('content') or []:
        if isinstance(b, dict) and b.get('type') == 'text' and isinstance(b.get('text'), str):
            text, _flag = screen_text(b['text'], 200_000)
            b = dict(b, text=text)
        blocks.append(b)
    out['content'] = blocks
    return out


def _format_result(tool, result: Any) -> Dict[str, Any]:
    """A tool's return value as a CallToolResult (the MCP handler's formatting, without the handler)."""
    if getattr(tool, 'passthrough_result', False):
        return tool.format_mcp_result(result, True)
    if isinstance(result, list) and result and all(isinstance(b, dict) and 'type' in b for b in result):
        return {'content': result}
    if isinstance(result, str):
        return {'content': [{'type': 'text', 'text': result}]}
    try:
        value = json.loads(json.dumps(result, default=str))
        text = json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        value, text = None, str(result)
    out: Dict[str, Any] = {'content': [{'type': 'text', 'text': text}]}
    schema = None
    try:
        schema = tool.output_schema
    except Exception:
        pass
    if isinstance(schema, dict) and schema.get('type') == 'object' and isinstance(value, dict):
        out['structuredContent'] = value
    if getattr(result, 'is_error', False):
        out['isError'] = True
    return out


_collector_added = False


def get_net_catalogs(svc) -> NetCatalogs:
    """The service's catalogs part, created on first use (metrics collector registered once)."""
    global _collector_added
    c = getattr(svc, 'catalogs', None)
    if c is None:
        c = NetCatalogs(svc, registry=getattr(svc, 'tools_registry', None))
        svc.catalogs = c
        try:
            reg = c.registry
            if reg is not None and hasattr(reg, 'add_reload_listener'):
                reg.add_reload_listener(c.reregister_after_reload)
        except Exception as e:
            logger.debug(f'SAJHA Net reload listener: {e}')
    if not _collector_added:
        try:
            from sajha.observability.metrics import REGISTRY

            def collect():
                cur = get_catalogs()
                return cur.metrics() if cur is not None else []
            REGISTRY.add_collector(collect)
            _collector_added = True
        except Exception as e:
            logger.debug(f'SAJHA Net catalog metrics: {e}')
    return c


def get_catalogs() -> Optional[NetCatalogs]:
    from sajha.net.integration import get_service
    svc = get_service()
    return getattr(svc, 'catalogs', None) if svc is not None else None


def check_local_call(name: str) -> None:
    """Raise :class:`LocalQuarantined` when local tool ``name`` may not run (one name, one contract)."""
    c = get_catalogs()
    if c is None:
        return
    q = c.local_quarantine(name)
    if q:
        raise LocalQuarantined(name, q)


def listed(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``tools/list`` without local tools quarantined in a net they are exported into."""
    c = get_catalogs()
    if c is None or not c.books:
        return tools
    return [t for t in tools if isinstance(t, dict) and (
        ((t.get('_meta') or {}).get(EXTENSION_ID) or {}).get('locality') == 'remote' or not c.local_quarantine(t.get('name', '')))]
