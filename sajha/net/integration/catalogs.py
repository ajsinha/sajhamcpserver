# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA Net catalogs and routing inside SAJHA (design §7, §8, §9, §15, §17.2, §17.4; protocol §10, §15).

* :class:`NativeCatalog` (catalog source ``native``): this server's own registry tools and the tools of
  its internal proxied MCP servers (under their federation names), never proxies of other members, with
  each tool's configured ``version``; external proxied servers' tools are published as
  ``<vendor>__<tool>``. Re-export (design §14, protocol §16) is
  separate: with ``reexport`` on for a net and a re-export rule matching, :meth:`NetCatalogs.reexports`
  offers into that net tools this server imported (from the same net, with ``origin``; from another
  net, as a bridge, as its own), and a call to one is relayed onward (:meth:`NetCatalogs._relay`).
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
``max_call_chain``, ``allow_remote_llm_tools``, ``reexport``, ``reexport_rules``, ``limits.*``, ``peer.*`` and
``plugins.routing``; ``default_trust``, ``reexport``, ``reexport_rules``, ``max_hops`` and
``refresh_interval_seconds`` may also be set in a net entry. Trust levels and
approvals set at runtime live in the storage backend (``<data_dir>/<net>/trust.json``).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.net import EXTENSION_ID, names, plugins
from sajha.net.catalog import TRUST_LEVELS, CatalogBook, Limits
from sajha.net.plugins import CatalogSource
from sajha.net.routing import (CODES, LOG, PROGRESS, CallContext, Candidate, HostRefusal, HostServer, PeerSettings,
                                Router, StreamSettings, origin_of)
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
    max_call_chain: int = 8            # hops plus nesting depth across the net, one budget (design §14)
    allow_remote_llm_tools: bool = True
    reexport: bool = False
    reexport_rules: List[Dict[str, Any]] = field(default_factory=list)   # which imported tools go onward (§14)
    routing: str = 'local_first'
    limits: Limits = field(default_factory=Limits)
    peer: PeerSettings = field(default_factory=PeerSettings)
    streaming: StreamSettings = field(default_factory=StreamSettings)
    host_calls_per_minute: int = 600
    anonymous_may_call_remote: bool = False
    per_net: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    external_servers: List[Any] = field(default_factory=list)      # ExternalServer (design §5.6)
    external_errors: List[str] = field(default_factory=list)

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
    s.max_call_chain = max(1, min(32, int(_num(_g('max_call_chain', 8), 8))))
    s.allow_remote_llm_tools = parse_bool(_g('allow_remote_llm_tools', 'true'), True)
    s.reexport = parse_bool(_g('reexport', 'false'), False)
    s.reexport_rules = [r for r in (raw.get('reexport_rules') or []) if isinstance(r, dict)]
    s.routing = str(_g('plugins.routing', 'local_first'))
    s.limits = Limits(max_tools_per_peer=int(_num(_g('limits.max_tools_per_peer', 2000), 2000)),
                      max_catalog_bytes=int(_num(_g('limits.max_catalog_bytes', 5242880), 5242880)),
                      max_description_chars=int(_num(_g('limits.max_description_chars', 1024), 1024)))
    s.peer = PeerSettings(timeout_seconds=s.default_timeout_seconds,
                          breaker_threshold=int(_num(_g('peer.breaker_threshold', 5), 5)),
                          breaker_reset_seconds=_num(_g('peer.breaker_reset_seconds', 30), 30),
                          calls_per_minute=int(_num(_g('peer.calls_per_minute', 600), 600)))
    s.host_calls_per_minute = int(_num(_g('peer.inbound_calls_per_minute', 600), 600))
    d = StreamSettings()
    st = StreamSettings(enabled=parse_bool(_g('streaming.enabled', 'true'), True),
                        max_events=max(1, int(_num(_g('streaming.max_events', d.max_events), d.max_events))),
                        max_event_bytes=max(1024, int(_num(_g('streaming.max_event_bytes', d.max_event_bytes),
                                                           d.max_event_bytes))),
                        max_stream_bytes=max(4096, int(_num(_g('streaming.max_stream_bytes', d.max_stream_bytes),
                                                            d.max_stream_bytes))),
                        idle_timeout_seconds=max(1.0, _num(_g('streaming.idle_timeout_seconds', d.idle_timeout_seconds),
                                                           d.idle_timeout_seconds)),
                        heartbeat_seconds=max(0.1, _num(_g('streaming.heartbeat_seconds', d.heartbeat_seconds),
                                                        d.heartbeat_seconds)),
                        progress_min_interval_ms=max(0, int(_num(_g('streaming.progress_min_interval_ms',
                                                                    d.progress_min_interval_ms),
                                                                 d.progress_min_interval_ms))))
    if st.heartbeat_seconds >= st.idle_timeout_seconds:      # a heartbeat must come before the home gives up
        st.heartbeat_seconds = max(0.1, st.idle_timeout_seconds / 3)
    s.streaming = st
    s.anonymous_may_call_remote = parse_bool(_g('anonymous_may_call_remote', 'false'), False)
    from sajha.net.integration.config import external_servers
    s.external_servers, s.external_errors = external_servers(raw)
    for entry in configured_nets():
        over = {}
        for k in ('default_trust', 'reexport', 'max_hops', 'refresh_interval_seconds', 'reexport_rules'):
            if entry.get(k) is not None:
                over[k] = entry[k]
        if 'reexport' in over:
            over['reexport'] = parse_bool(over['reexport'], False)
        if 'reexport_rules' in over:
            over['reexport_rules'] = [r for r in (over['reexport_rules'] or []) if isinstance(r, dict)]
        if over:
            s.per_net[str(entry.get('name') or 'default')] = over
    return s


# ── the catalog source ──────────────────────────────────────────────

def _registry():
    from sajha.tools.tools_registry import get_tools_registry
    return get_tools_registry()


def _own_tools(reg, external_upstreams=frozenset()) -> List[BaseMCPTool]:
    """This server's registry tools offered into a net under their own names: its native tools and
    the tools of its INTERNAL proxied MCP servers (owner decision: an internal proxied server keeps its
    tool names and is governed like a local tool, so one name, one contract applies to it). Proxies of
    other members, and the tools of EXTERNAL proxied servers (offered separately as <vendor>__<tool>,
    see :func:`_external_tools`), are left out."""
    from sajha.federation.tool import FederatedTool
    with reg._tools_lock:
        items = list(reg.tools.values())
    return [t for t in items if t.enabled and not isinstance(t, NetProxyTool)
            and not (isinstance(t, FederatedTool) and getattr(t, 'upstream_id', None) in external_upstreams)]


def _external_tools(reg, servers: List[Any], net: str) -> List[Tuple[Any, Any]]:
    """``(federated tool, external server)`` for every tool of an external server offered into ``net``
    (design §5.6): an enabled federation tool of a listed upstream that the server's ``tools`` globs name."""
    import fnmatch
    if not servers:
        return []
    try:
        from sajha.federation.tool import FederatedTool
    except Exception:
        return []
    by_up = {x.upstream: x for x in servers if not x.nets or net in x.nets}
    with reg._tools_lock:
        items = list(reg.tools.values())
    out = []
    for t in items:
        x = by_up.get(getattr(t, 'upstream_id', None)) if isinstance(t, FederatedTool) and t.enabled else None
        part = str(getattr(t, 'upstream_name', '') or '') if x is not None else ''
        if part and any(fnmatch.fnmatchcase(part, p) for p in x.tools):
            out.append((t, x))
    return out


@plugins.register('catalog_source')
class NativeCatalog(CatalogSource):
    """This server's own registry tools as MCP Tool objects, with their versions, and the tools of the
    external servers it defines, published as ``<vendor>__<tool>`` (design §5.6)."""
    name = 'native'

    def __init__(self, registry=None, allow_llm_tools: Any = True, external: Any = None):
        self._registry = registry
        self._allow_llm = allow_llm_tools          # bool, or a callable (sajhanet.allow_remote_llm_tools)
        self._external = external                  # ExternalServer list, or a callable returning one

    def external_servers(self) -> List[Any]:
        x = self._external() if callable(self._external) else self._external
        return list(x or [])

    def tools(self, net, peer=None):
        reg = self._registry or _registry()
        if reg is None:
            return []
        out = self._own(reg)
        for tool, x in _external_tools(reg, self.external_servers(), net):
            try:
                d = copy.deepcopy(tool.to_mcp_format())
            except Exception as e:
                logger.debug(f'SAJHA Net catalog: external {getattr(tool, "name", "?")}: {e}')
                continue
            meta = dict(d.get('_meta') or {})
            meta.pop('sajha/federation', None)
            if meta:
                d['_meta'] = meta
            else:
                d.pop('_meta', None)
            extra: Dict[str, Any] = {'version': str(getattr(tool, 'version', '') or ''), 'vendor': x.vendor,
                                     'external': True, 'publish_as': x.published(str(tool.upstream_name))}
            try:
                from sajha.net.integration.residency import catalog_summary
                dc = catalog_summary(tool)
                if dc:
                    extra['data_classes'] = dc
            except Exception as e:
                logger.debug(f'SAJHA Net external residency summary of {tool.name}: {e}')
            d['_net'] = {k: v for k, v in extra.items() if v not in ('', None)}
            out.append(d)
        return out

    def _own(self, reg) -> List[Dict[str, Any]]:
        out = []
        external = frozenset(x.upstream for x in self.external_servers())
        for tool in _own_tools(reg, external):
            try:
                d = tool.to_mcp_format()
            except Exception as e:
                logger.debug(f'SAJHA Net catalog: {getattr(tool, "name", "?")}: {e}')
                continue
            cfg = getattr(tool, 'config', None) or {}
            meta_cat = str(((cfg.get('metadata') or {}).get('category')) or '')
            extra: Dict[str, Any] = {'version': str(getattr(tool, 'version', '') or cfg.get('version') or '')}
            if meta_cat == 'llm' or cfg.get('llm') or cfg.get('type') == 'llm':
                allow = self._allow_llm() if callable(self._allow_llm) else self._allow_llm
                if not allow:
                    continue                          # sajhanet.allow_remote_llm_tools: false
                extra['llm_tool'] = True
            from sajha.net.integration.residency import catalog_summary
            dc = catalog_summary(tool)                     # residency: the classes of its arguments and results
            if dc:
                extra['data_classes'] = dc
            d['_net'] = {k: v for k, v in extra.items() if v not in ('', None)}
            out.append(d)
        return out


# ── proxy tools ─────────────────────────────────────────────────────

def _caller_user(net_hint: str = '') -> Dict[str, Any]:
    from sajha.observability.caller import current
    c = current()
    # ``Caller.api_key`` is the key's NAME (for the usage ledger), never the key: the raw key a caller
    # presented is held per request by sajha/auth/presented_key.py, which NetAuthz.key_for reads.
    return {'user_id': c.user_id, 'roles': list(c.roles), 'is_admin': c.is_admin, 'auth_type': c.auth_type,
            'api_key_name': c.api_key, 'authenticated': c.user_id not in ('', 'anonymous'), 'net': net_hint}


class NetProxyTool(BaseMCPTool):
    """A remote tool in this server's registry (see the module docstring)."""
    passthrough_result = True
    namespaced_name = True          # <net>__<instance>__<tool> and published aliases (sajha/tools/naming.py)

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
        book = CatalogBook(node, NativeCatalog(self._registry,
                                               allow_llm_tools=lambda: self.settings.allow_remote_llm_tools,
                                               external=self.external_servers),
                           rules=rules,
                           trust_of=lambda peer, net=net: self.trust_of(net, peer),
                           approvals=lambda peer, net=net: self.approvals(net, peer),
                           screen_text=screen_text, schema_problem=schema_problem, limits=s.limits,
                           refresh_interval=float(s.for_net(net, 'refresh_interval_seconds')),
                           default_trust=str(s.for_net(net, 'default_trust')),
                           reexport=bool(s.for_net(net, 'reexport')),
                           run_ttl=max(60.0, self.svc.shared.agent_lease_seconds * 4),
                           reexports=lambda peer, net=net: self.reexports(net, peer)).attach()
        if book.reexport and 'reexport' not in node.extra_features:
            node.extra_features.append('reexport')          # protocol §6.2: offers imported tools onward here
        if s.streaming.enabled:                             # §6.2, §15.10: signed event streams on forwarded calls
            for f in ('streaming', 'progress', 'cancellation'):
                if f not in node.extra_features:
                    node.extra_features.append(f)
        node.observers.append(lambda kind, data, net=net: self._on_event(net, kind, data))
        book.start()
        self.books[net] = book
        host = HostServer(book, execute=self._execute, identity=identity, rules=rules,
                          max_hops=int(s.for_net(net, 'max_hops')), max_chain=s.max_call_chain,
                          own_identities=lambda: [f'{n}/{b.node.name}' for n, b in self.books.items()],
                          other=lambda msg, v, net=net: self._other(net, msg, v),
                          calls_per_minute=s.host_calls_per_minute, audit=self._audit,
                          streaming=s.streaming).attach()
        self.hosts[net] = host
        self._build_router()
        return book

    def external_servers(self) -> List[Any]:
        """The external servers this instance defines (design §5.6): ``sajhanet.external_servers``, then the
        external entries of federation's mcpServers file (an upstream listed in both: the first wins)."""
        cands = list(self.settings.external_servers or [])
        fed_prefixes: Dict[str, str] = {}
        try:
            from sajha.federation.manager import get_federation
            fed = get_federation()
            extra = fed.external_servers() if fed is not None and hasattr(fed, 'external_servers') else []
            for uid in (fed.upstream_ids() if fed is not None else []):
                fed_prefixes[fed.get_config(uid).effective_prefix] = uid
        except Exception as e:
            logger.debug(f'SAJHA Net: external servers of federation: {e}')
            extra = []
        if extra:
            from sajha.net.integration.config import ExternalServer
            have = {x.upstream for x in cands}
            for d in extra:
                if d.get('upstream') in have:
                    continue
                try:
                    cands.append(ExternalServer.from_dict(d))
                except ValueError as e:
                    logger.warning(f'SAJHA Net: external server {d.get("upstream")}: {e}')
        # prefixes are unique on an instance: across upstreams and external servers, never a local tool's name
        local = set(self._local_names())
        out, used, problems = [], {}, []
        for x in cands:
            p = x.effective_prefix
            other = fed_prefixes.get(p)
            if p in used:
                problems.append(f'prefix {p} of external server {x.upstream} is already used by external server '
                                f'{used[p]}; {x.upstream} is not offered')
            elif other is not None and other != x.upstream:
                problems.append(f'prefix {p} of external server {x.upstream} is the prefix of federation upstream '
                                f'{other}; {x.upstream} is not offered')
            elif p in local:
                problems.append(f'prefix {p} of external server {x.upstream} is the name of a local tool; '
                                f'{x.upstream} is not offered')
            else:
                used[p] = x.upstream
                out.append(x)
        if problems != getattr(self, '_external_problems', None):
            self._external_problems = problems
            from sajha.net.integration import _clear, _notice
            errs = list(self.settings.external_errors or []) + problems
            if errs:
                for e in problems:
                    logger.error(f'SAJHA Net: {e}')
                _notice('sajhanet.external_servers', 'warning', 'Some external servers are not offered',
                        '; '.join(errs)[:1000], ttl=0)
            else:
                _clear('sajhanet.external_servers')
        return out

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
                             screen_result=_screen_result, max_hops=self.settings.max_hops,
                             max_chain=self.settings.max_call_chain, streaming=self.settings.streaming)

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
        for b in list(self.books.values()):
            if b.reexport:                     # what this server re-exports follows what it imports
                try:
                    b._recompute_digest()
                except Exception as e:
                    logger.debug(f'SAJHA Net {b.net}: re-export digest: {e}')
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
        from sajha.core import inner_calls
        hop_in, depth = inner_calls.outgoing()      # a call made while serving a forwarded one continues its chain
        out = self.router.call(name, arguments, user=user, traceparent=tp, hop_in=hop_in, depth=depth,
                               **stream_hooks(self._event_rule(name, user)))
        return self._arrived(name, out, user)

    def _event_rule(self, name: str, user: Dict[str, Any]):
        """Residency on each streamed event as it arrives (``residency.on_event``), for the proxy ``name``."""
        proxy = self._proxies.get(name)
        if proxy is None:
            return None
        from sajha.net.integration.residency import on_event
        node = next(iter(self.books.values())).node if self.books else None
        return lambda ev: on_event(node, proxy, ev, user)

    def _arrived(self, name: str, out: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
        """Residency on a result as it arrives (design §12): this server's own rules, redaction and classes."""
        try:
            from sajha.net.integration.residency import on_arrival
            meta = ((out or {}).get('_meta') or {}).get(EXTENSION_ID) or {}
            book = self.books.get(str(meta.get('net') or ''))
            proxy = self._proxies.get(name)
            if book is not None and proxy is not None and not (out or {}).get('isError'):
                return on_arrival(book.node, proxy, out, user)
        except Exception as e:
            logger.warning(f'SAJHA Net residency on arrival for {name}: {e}; the result is withheld')
            return {'content': [{'type': 'text', 'text': f'This server could not check the residency of the result '
                                                         f'of {name}; it is withheld.'}], 'isError': True}
        return out

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
        rx = ctx.reexport
        local = ctx.local_tool or ctx.tool                 # §5.5: the call names the published name
        tool = reg.get_tool(local) if reg is not None and rx is None else None
        if rx is None and (tool is None or isinstance(tool, NetProxyTool)):
            raise HostRefusal('export')
        return self.execute_tool(ctx, arguments, tool, local_name=local if rx is None else '')

    def execute_tool(self, ctx: CallContext, arguments: Dict[str, Any], tool, local_name: str = '') -> Dict[str, Any]:
        """Steps 10 and 11 for ``tool`` (a registry tool; None for a re-exported call): access under
        ``local_name`` (default the tool's name in the call), policy, approvals, then the tool. A
        sponsored participant's host runs its calls here (sajha/net/integration/sponsored.py)."""
        rx = ctx.reexport
        from sajha.observability.caller import Caller, reset, set_caller
        user = ctx.user or {}
        roles = tuple(user.get('roles') or ())
        uid = str(user.get('user_id') or user.get('name') or f'sajhanet:{ctx.net}/{ctx.peer}')
        access = None
        if ctx.user is not None:
            a = getattr(self.svc, 'authz', None)
            db = None
            try:
                from sajha.auth import AuthContext
                from sajha.auth.access import policy_for
                if a is not None and hasattr(a, 'auth_context') and hasattr(a, 'db'):
                    # the local account's roles and their permissions come from this server's database
                    db = a.db()
                    auth = a.auth_context(dict(user, user_id=uid, roles=list(roles)), db)
                else:
                    auth = AuthContext(authenticated=True, user_id=uid, user_name=str(user.get('user_name_local') or uid),
                                       roles=list(roles), auth_type='sajhanet', is_admin='admin' in roles,
                                       api_key_mode=user.get('tool_access_mode') or None,
                                       api_key_tools=json.dumps(user.get('tool_access_list') or []))
                access = policy_for(auth).can_execute
            except Exception as e:
                logger.warning(f'SAJHA Net: access policy for {uid}: {e}')
                raise HostRefusal('access')
            finally:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
            source = ((rx or {}).get('_source') or {}).get('qualified_name')
            if not access(local_name or ctx.tool) and not access(ctx.tool) and not (source and access(source)):
                raise HostRefusal('access')
        if rx is not None:
            token = set_caller(Caller(uid, '', roles, 'sajhanet', access, 'admin' in roles))
            try:
                return self._relay(ctx, rx, arguments)
            finally:
                reset(token)
        token = set_caller(Caller(uid, '', roles, 'sajhanet', access, 'admin' in roles))
        from sajha.core import inner_calls
        try:
            last = _llm_last_run()
            if last is not None:
                last.set(None)
            with inner_calls.net_entered(ctx.hop, ctx.visited, ctx.depth):
                out = self._run_tool(tool, ctx, arguments)
            info = last.get() if last is not None else None
            if info is not None and getattr(info, 'usage', None) is not None and isinstance(out, dict):
                out = _with_remote_usage(out, info)
            return out
        finally:
            reset(token)

    def _run_tool(self, tool, ctx: CallContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
        from sajha.core.inner_calls import CallTooDeep
        from sajha.core.mcp_mrtr import InputRequired
        from sajha.policy.errors import PolicyError
        from sajha.tools.base_mcp_tool import ToolArgumentError
        try:
            result = tool.execute_with_tracking(arguments)
        except PolicyError as e:
            raise HostRefusal('approval_required' if e.kind == 'approval_required' else 'policy')
        except CallTooDeep as e:                # the combined budget (sajhanet.max_call_chain) ran out here
            raise HostRefusal('chain_limit', str(e), executed=not str(e).startswith(f'calling {tool.name} '))
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
                ext = net_extension.extension_object(net) or {}
                if 'instance' not in ext:            # nets not in the YAML (built in code): the node's own view
                    try:
                        ext = self.svc.participant.extension(net)
                    except Exception:
                        pass
                if method == 'initialize':           # CAP-02: the 2025-11-25 result carries it under experimental
                    info: Dict[str, Any] = {}
                    try:
                        from sajha.app import mcp_handler
                        if mcp_handler is not None:
                            info = copy.deepcopy(mcp_handler.server_info)
                    except Exception as e:
                        logger.debug(f'SAJHA Net initialize: {e}')
                    info = info if isinstance(info, dict) and info else {
                        'protocolVersion': '2025-11-25', 'serverInfo': {'name': 'sajha', 'version': ''}}
                    caps = info.setdefault('capabilities', {})
                    caps.setdefault('tools', {})
                    caps.setdefault('experimental', {})[EXTENSION_ID] = ext
                    return {'jsonrpc': '2.0', 'id': rid, 'result': info}
                return {'jsonrpc': '2.0', 'id': rid, 'result': {
                    'supportedVersions': ['2026-07-28', '2025-11-25'],
                    'capabilities': {'extensions': {EXTENSION_ID: ext}, 'tools': {}}}}
        return {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32601, 'message': f'{method} is not served to net peers'}}

    # ── re-export (design §14, protocol §16) ───────────────────────

    def _rule(self, net: str, row: Dict[str, Any], peer: Optional[str],
              roles: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """The first re-export rule of ``net`` that lets ``row`` (a host and tool table row) go to ``peer``
        (None: any peer) for a user with ``roles`` (None: catalog time). A rule with an empty
        ``to_instances`` re-exports its tools to nobody, whatever other rules say."""
        from sajha.net.integration.authz import _any, _list, _roles_ok
        hit = None
        for r in self.settings.for_net(net, 'reexport_rules') or []:
            if not _any(row['host_tool'], _list(r.get('tools'))) and not _any(row['part'], _list(r.get('tools'))):
                continue
            if not _any(row['net'], _list(r.get('from_nets')) or ['*']):
                continue
            if not _any(row['host_instance'], _list(r.get('from_instances')) or ['*']):
                continue
            to = r.get('to_instances')
            if to is not None and not _list(to):
                return None
            if peer is not None and not _any(peer, _list(to) or ['*']):
                continue
            if not _roles_ok(roles, r.get('for_roles')):
                continue
            hit = hit or r
        return hit

    def reexports(self, net: str, peer: Optional[str] = None) -> List[Dict[str, Any]]:
        """The tools this server re-exports into ``net`` to ``peer`` (None: any peer), as tool objects with
        ``_net`` (``origin`` for a tool of the same net) and ``_source`` (where a call goes). One tool per
        name: the first host in resolution order (direct offers before re-exported ones); never a name of a
        local tool, never a tool back to its host or origin, never a tool whose origin is this server."""
        router = self.router
        if router is None or not self.settings.for_net(net, 'reexport') or \
                not self.settings.for_net(net, 'reexport_rules'):
            return []
        b = self.books.get(net)
        if b is None:
            return []
        me = b.node.name
        local = set(self._local_names())
        order = {n: i for i, n in enumerate(bk.net for bk in router.books)}
        by_part: Dict[str, List[Dict[str, Any]]] = {}
        for r in router.rows():
            if r['state'] == 'active' and r['part'] not in local:
                by_part.setdefault(r['part'], []).append(r)
        out = []
        for part in sorted(by_part):
            rows = sorted(by_part[part], key=lambda r: (order.get(r['net'], 99), bool(origin_of(r)), r['host_instance']))
            for r in rows:
                within = r['net'] == net
                origin = (origin_of(r) or r['host_instance']) if within else ''
                if within and (origin == me or (peer is not None and peer in (origin, r['host_instance']))):
                    continue
                try:
                    c = Candidate(net=r['net'], host=r['host_instance'], host_tool=r['host_tool'],
                                  qualified_name=r['qualified_name'], part=part, contract_hash=r['contract_hash'],
                                  state=r['state'], book=self.books.get(r['net']), row=r)
                    if router._ineligible(c, None):
                        continue                              # import rules, residency, quarantine
                except Exception:
                    continue
                if self._rule(net, r, peer) is None:
                    continue
                out.append(self._reexported_tool(r, origin))
                break
        return out

    @staticmethod
    def _reexported_tool(r: Dict[str, Any], origin: str) -> Dict[str, Any]:
        """The catalog entry of a re-exported tool: the host's contract unchanged (so its contract hash is the
        same, §10.7), the description as screened here."""
        e = r['entry']
        d = e.get('definition') or {}
        contract = e.get('contract') or {}
        tool: Dict[str, Any] = {'name': r['host_tool'], 'description': d.get('description') or '',
                                'inputSchema': copy.deepcopy(contract.get('inputSchema') or
                                                             {'type': 'object', 'properties': {}}),
                                'annotations': copy.deepcopy(contract.get('annotations') or {})}
        if contract.get('outputSchema'):
            tool['outputSchema'] = copy.deepcopy(contract['outputSchema'])
        if d.get('title'):
            tool['title'] = d['title']
        meta = e.get('meta') or {}
        extra = {k: meta[k] for k in ('version', 'data_classes', 'llm_tool', 'vendor', 'external')
                 if meta.get(k) is not None}
        if origin:
            extra['origin'] = origin
        tool['_net'] = extra
        tool['_source'] = {'net': r['net'], 'host': r['host_instance'], 'qualified_name': r['qualified_name'],
                           'origin': origin or None, 'contract_hash': r['contract_hash']}
        return tool

    def reexport_decision(self, net: str, s: Dict[str, Any]) -> plugins.Decision:
        """The ``reexport`` rule at call time (protocol §15.4 step 9 for a re-exported tool): a re-export rule
        for this peer and this user's local roles, and the key's tool access as a ceiling."""
        src = s.get('source') or {}
        router = self.router
        row = next((r for r in (router.rows() if router else []) if r['qualified_name'] == src.get('qualified_name')),
                   None)
        if row is None:
            return plugins.Decision(False, 'export')
        u = s.get('user') if isinstance(s.get('user'), dict) else None
        if self._rule(net, row, str(s.get('peer') or ''), list(u.get('roles') or []) if u else None) is None:
            return plugins.Decision(False, 'export')
        from sajha.net.integration.authz import key_allows
        b = self.books.get(net)
        if u is not None and b is not None and not key_allows(u, net, b.node.name, str(s.get('tool') or '')):
            return plugins.Decision(False, 'access')
        return plugins.Decision(True, 'reexport')

    def _relay(self, ctx: CallContext, rx: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Run a re-exported tool: within one net, forward the call to its origin with the caller's assertion
        unchanged; across nets (a bridge), call into the other net as the local user the caller was mapped
        to, with an assertion this server signs there (protocol §16). Hops, visited list and depth continue;
        residency and the combined chain budget apply on every step."""
        src = rx.get('_source') or {}
        q = str(src.get('qualified_name') or '')
        within = src.get('net') == ctx.net
        user = dict(ctx.user or {})
        relay = None
        if within:
            if not ctx.relay:
                raise HostRefusal('assertion_invalid')
            relay = dict(ctx.relay)
        else:
            if ctx.user is None or user.get('guest'):
                raise HostRefusal('no_account', 'a bridge calls into another net only as one of its own users')
            user.update(_bridge=True, net=str(src.get('net') or ''), authenticated=True)
        out = self.router.call(q, dict(arguments or {}), user=user, traceparent=ctx.traceparent,
                               hop_in=(ctx.hop, list(ctx.visited)), depth=ctx.depth, relay=relay,
                               **stream_hooks(self._event_rule(q, user)))   # the next hop's events re-signed here
        meta = ((out or {}).get('_meta') or {}).get(EXTENSION_ID) or {}
        rf = meta.get('refusal')
        if (out or {}).get('isError') and isinstance(rf, dict) and rf.get('executed') is False \
                and rf.get('reason') in CODES:
            raise HostRefusal(str(rf['reason']), executed=False,
                              refused_by=str(rf.get('refused_by') or rf.get('instance') or '') or None)
        out = self._arrived(q, out, user)
        m = dict(((out or {}).get('_meta') or {}).get(EXTENSION_ID) or {})
        m['via'] = {'net': src.get('net'), 'instance': src.get('host'), 'origin': src.get('origin')}
        return dict(out, _meta=dict((out or {}).get('_meta') or {}, **{EXTENSION_ID: m}))

    # ── topology (design §17; the console renders it) ──────────────

    def topology(self, net: Optional[str] = None) -> Dict[str, Any]:
        """Per net: the instances (this server and every member it holds) and the edges this server
        knows: ``offers`` (own tools offered to a peer, or a peer's own tools offered here), ``reexports``
        (tools offered onward, with their origins) and ``calls`` (call paths observed here since this
        process started: calls this server sent, and the steps of every chain that reached it)."""
        out = []
        for n, b in self.books.items():
            if net and n != net:
                continue
            node = b.node
            me = node.name
            cfg = node.cfg
            nodes = [{'name': me, 'kind': cfg.kind, 'region': cfg.region or '', 'state': 'alive', 'self': True,
                      'vendor': cfg.vendor}]
            for m in node.members():
                rec = m.get('record') or {}
                nodes.append({'name': m['name'], 'kind': rec.get('kind') or '', 'region': rec.get('region') or '',
                              'state': m.get('state') or '', 'self': False, 'vendor': rec.get('vendor') or ''})
                if rec.get('sponsor'):                   # a sponsored member names its sponsor (design §5.1)
                    nodes[-1]['sponsor'] = rec['sponsor']
            edges: List[Dict[str, Any]] = []
            for peer, held in sorted(b.live_peers().items()):
                direct = [e for e in held.get('tools') or [] if not (e.get('meta') or {}).get('origin')]
                via = [e for e in held.get('tools') or [] if (e.get('meta') or {}).get('origin')]
                if direct:
                    edges.append({'from': peer, 'to': me, 'kind': 'offers', 'tools': len(direct), 'calls': 0})
                if via:
                    edges.append({'from': peer, 'to': me, 'kind': 'reexports', 'tools': len(via), 'calls': 0,
                                  'origins': sorted({str(e['meta']['origin']) for e in via})})
            for m in node.members():
                if m.get('state') not in ('alive', 'suspect'):
                    continue
                try:
                    tools = b.exports(m['name'])
                except Exception:
                    continue
                own = [t for t in tools if b.reexport_of(t['name'], m['name']) is None]
                rx = [b.reexport_of(t['name'], m['name']) for t in tools]
                rx = [t for t in rx if t is not None]
                if own:
                    edges.append({'from': me, 'to': m['name'], 'kind': 'offers', 'tools': len(own), 'calls': 0})
                if rx:
                    edges.append({'from': me, 'to': m['name'], 'kind': 'reexports', 'tools': len(rx), 'calls': 0,
                                  'origins': sorted({str(((t.get('_net') or {}).get('origin')) or
                                                         f'{(t.get("_source") or {}).get("net")}/'
                                                         f'{(t.get("_source") or {}).get("host")}') for t in rx})})
            calls: Dict[Tuple[str, str], Dict[str, Any]] = {}
            sources = [self.router.paths] if self.router is not None else []
            if n in self.hosts:
                sources.append(self.hosts[n].paths)
            for p in sources:
                for e in p.edges(n):
                    c = calls.setdefault((e['from'], e['to']), {'calls': 0, 'tools': set()})
                    c['calls'] += e['calls']
                    c['tools'].update(e['tools'])
            for (f, t), c in sorted(calls.items()):
                edges.append({'from': f, 'to': t, 'kind': 'calls', 'tools': len(c['tools']), 'calls': c['calls']})
            out.append({'name': n, 'nodes': nodes, 'edges': edges})
        return {'nets': out}

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
        elif kind == 'tool_name_refused':                # §5.5: an own tool whose published name cannot be used
            _notice(f'sajhanet.name:{net}:{data.get("tool")}', 'warning',
                    f'Tool {data.get("tool")} is not offered in {net}', data.get('detail') or '', ttl=0)
            _audit('tool_name_refused', details={'net': net, 'tool': data.get('tool'),
                                                 'published': data.get('published'), 'detail': data.get('detail')})
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
            row = {k: v for k, v in r.items() if k not in ('entry', 'member')}
            meta = (r.get('entry') or {}).get('meta') or {}
            rec = (r.get('member') or {}).get('record') or {}
            # design §5.6: an external server's tool names its vendor; else the host's vendor
            row['external'] = bool(meta.get('external'))
            row['vendor'] = (meta.get('vendor') if row['external'] else rec.get('vendor')) or ''
            try:
                from sajha.net.integration.residency import _entry_classes
                row['data_classes'] = _entry_classes(r.get('entry'), r['host_tool'], r['qualified_name']).summary()
            except Exception:
                row['data_classes'] = {}
            rows.append(row)
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


def stream_hooks(rule: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """The streaming arguments of :meth:`Router.call` for the tool context running now (protocol §15.10): a
    verified event from the host is relayed into ``current_context()`` (progress under the caller's own
    token, log at the caller's level; text screened and capped), and the caller's cancellation closes the
    stream. With no tool context the call still streams (heartbeats, cancellation) but relays nothing.
    ``rule``: this server's residency on each event first (``residency.on_event``; None drops it)."""
    from sajha.core import mcp_tool_context as mtc
    ctx = mtc.current_context()
    hooks: Dict[str, Any] = {'cancelled': mtc.is_cancelled}
    if ctx is None:
        return hooks

    def on_event(ev: Dict[str, Any]) -> None:
        from sajha.federation.security import screen_text
        if rule is not None:
            ev = rule(ev)
            if ev is None:
                return
        p = ev.get('params') or {}
        if ev.get('method') == PROGRESS:
            prog, total = p.get('progress'), p.get('total')
            if not isinstance(prog, (int, float)) or isinstance(prog, bool):
                return
            if not isinstance(total, (int, float)) or isinstance(total, bool):
                total = None
            msg = p.get('message')
            msg = screen_text(msg, 2000)[0] if isinstance(msg, str) and msg else None
            ctx.emit_progress(prog, total, msg)
        elif ev.get('method') == LOG:
            level = p.get('level')
            if level not in mtc.LOG_LEVELS:
                return
            data = p.get('data')
            if isinstance(data, str):
                data = screen_text(data, 8000)[0]
            lg = p.get('logger')
            ctx.emit_log(level, data, lg[:200] if isinstance(lg, str) else None)
    hooks.update(on_event=on_event, progress=ctx.progress_token is not None, log_level=ctx.log_level)
    return hooks


def _llm_last_run():
    """The context variable holding an LLM tool's last top-level run (its usage), when LLM tools load."""
    try:
        from sajha.ai.llm_tools.tool import LAST_RUN
        return LAST_RUN
    except Exception:
        return None


def _with_remote_usage(result: Dict[str, Any], info: Any) -> Dict[str, Any]:
    """An LLM tool's model spend on this server, reported to the home in ``_meta["io.sajha/net"].usage``
    (design §13): charged here, to this server's budgets, never again at the home."""
    u = info.usage
    usage = {'tokens': int(getattr(u, 'total_tokens', 0) or 0), 'cost_usd': round(float(getattr(u, 'cost_usd', 0) or 0), 6),
             'models': [str(m) for m in (getattr(info, 'models', None) or [])][:8], 'charged_by': 'host'}
    meta = dict((result.get('_meta') or {}).get(EXTENSION_ID) or {})
    meta['usage'] = usage
    return dict(result, _meta=dict(result.get('_meta') or {}, **{EXTENSION_ID: meta}))


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
    from sajha.net.integration.residency import offered
    return [t for t in tools if isinstance(t, dict) and (
        (((t.get('_meta') or {}).get(EXTENSION_ID) or {}).get('locality') == 'remote' and offered(t.get('name', '')))
        or (((t.get('_meta') or {}).get(EXTENSION_ID) or {}).get('locality') != 'remote'
            and not c.local_quarantine(t.get('name', ''))))]
