"""
The SAJHA Net agent: any MCP server as a full SAJHA Net participant (design §5.1, kind ``agent``).

The agent is the reference library (:mod:`sajha.net.library`) in front of one MCP server: it holds
the participant's identity (a self-signed certificate under ``admission: open`` or manual mode, or a
certificate from the net's CA through enrollment), gossips, publishes the server's ``tools/list`` as
its catalog with net metadata, verifies forwarded users (``api_key``, ``assertion``,
``token_exchange``: :mod:`sajhanet_agent.identity`), applies its export policy, blocks and residency
rules (:mod:`sajhanet_agent.rules`), and passes allowed calls to the server. With users in its
configuration file (:mod:`sajhanet_agent.config`) and a client listener it is also a home
(:mod:`sajhanet_agent.home`): its local clients call other members' tools through it, and it can
re-export what it imports.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sajha.net import jcs
from sajha.net import residency as R
from sajha.net.blocks import BlockPublication
from sajha.net.library import CallContext, ExportPolicy, HostRefusal, NetParticipant
from sajha.net.models import GossipSettings
from sajha.net.plugins import CatalogSource

from sajhanet_agent.config import PolicyFile
from sajhanet_agent.identity import TOKEN_PATH, AgentIdentity, FileKeyDirectory, own_key_bodies
from sajhanet_agent.rules import AgentRules

from sajhanet_agent.mcp_client import (CallableMCPClient, HttpMCPClient, MCPClient, MCPError, MCPUnavailable,
                                       StdioMCPClient)

logger = logging.getLogger('sajhanet_agent')


@dataclass
class AgentConfig:
    net: str
    instance: str
    url: str                                   # the address peers reach this agent at (its base URL)
    seeds: List[str] = field(default_factory=list)
    founder: bool = False
    admission: str = 'open'                    # open | builtin_ca | manual
    ca_url: str = ''
    token: str = ''
    pins: List[str] = field(default_factory=list)
    data_dir: str = 'data/sajhanet-agent'
    require_https: bool = True
    region: str = ''
    labels: Dict[str, str] = field(default_factory=dict)
    export_tools: List[str] = field(default_factory=lambda: ['*'])
    export_peers: List[str] = field(default_factory=lambda: ['*'])
    export_roles: Optional[List[str]] = None
    service_calls: bool = False
    verify_keys: bool = True
    mcp_command: str = ''
    mcp_url: str = ''
    mcp_headers: Dict[str, str] = field(default_factory=dict)
    call_timeout_seconds: float = 60.0
    catalog_refresh_seconds: float = 60.0
    gossip_interval_ms: int = 1000
    vendor: str = ''                           # the organisation answering for the server's tools (§5.5)
    rename: Dict[str, str] = field(default_factory=dict)   # local tool -> published name
    config_path: str = ''                      # the configuration file (users, identity, rules; config.py)
    home: bool = False                         # serve local clients: import other members' tools (home.py)


class McpCatalog(CatalogSource):
    """The fronted server's ``tools/list``, cached; on failure the last good list is kept."""
    name = 'mcp_tools_list'

    def __init__(self, client: MCPClient, refresh_seconds: float = 60.0, clock: Callable[[], float] = time.time,
                 annotate: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None):
        self.client = client
        self.annotate = annotate
        self.refresh = max(1.0, float(refresh_seconds))
        self.clock = clock
        self._tools: List[Dict[str, Any]] = []
        self._at = float('-inf')
        self._lock = threading.Lock()
        self.error = ''

    def invalidate(self) -> None:
        self._at = float('-inf')

    def tools(self, net, peer=None):
        with self._lock:
            if self.clock() - self._at >= self.refresh:
                try:
                    self._tools = [_clean(t) for t in self.client.list_tools()]
                    self.error = ''
                except Exception as e:
                    self.error = str(e)
                    logger.warning(f'tools/list on the fronted MCP server failed: {e}; keeping {len(self._tools)} tools')
                self._at = self.clock()
            tools = [dict(t) for t in self._tools]
        if self.annotate is not None:
            for t in tools:
                extra = self.annotate(t)
                if extra:
                    t['_net'] = extra
        return tools

    def definition(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return next((dict(t) for t in self._tools if t.get('name') == name), None)


def _clean(tool: Dict[str, Any]) -> Dict[str, Any]:
    keep = ('name', 'title', 'description', 'inputSchema', 'outputSchema', 'annotations', '_meta')
    return {k: tool[k] for k in keep if k in tool}


def make_client(cfg: AgentConfig) -> MCPClient:
    if bool(cfg.mcp_command) == bool(cfg.mcp_url):
        raise ValueError('give exactly one of --mcp-command and --mcp-url')
    if cfg.mcp_command:
        return StdioMCPClient(cfg.mcp_command)
    return HttpMCPClient(cfg.mcp_url, headers=cfg.mcp_headers)


class Agent:
    """One fronted MCP server in one net."""

    def __init__(self, cfg: AgentConfig, client: Optional[MCPClient] = None, *, connector=None,
                 clock: Callable[[], float] = time.time, gossip: Optional[GossipSettings] = None, kv=None,
                 audit: Optional[Callable[[str, Dict[str, Any]], None]] = None):
        self.cfg = cfg
        self.audit = audit
        self.policy_file = PolicyFile(cfg.config_path)
        pol = self.policy_file.policy
        if pol.users and not cfg.verify_keys:
            raise ValueError('the configuration file lists users, whose keys this agent publishes in the net key '
                             'directory: remove --no-key-verification')
        self.client = client or make_client(cfg)
        self.catalog = McpCatalog(self.client, cfg.catalog_refresh_seconds, clock, annotate=self._classes)
        export = ExportPolicy(tools=cfg.export_tools, peers=cfg.export_peers, roles=cfg.export_roles,
                              service_calls=cfg.service_calls, host=cfg.instance)
        self.identity = AgentIdentity(self.policy)
        self.rules = AgentRules(export, self.policy, lambda: self.participant.node, local_tool=self._local_tool,
                                reexport_row=lambda q: self.home.row(q) if self.home else None,
                                importing=lambda: self.importing, audit=audit)
        self.home = None
        extra: Dict[str, Any] = {'kv': kv} if kv is not None else {}
        if cfg.verify_keys:
            extra['identity'] = self.identity
            extra['key_store'] = FileKeyDirectory(os.path.join(cfg.data_dir, 'own_keys.json') if cfg.data_dir else '',
                                                  lambda: cfg.instance)
        self.participant = NetParticipant.build(
            net=cfg.net, instance=cfg.instance, base_url=cfg.url, source=self.catalog, execute=self._execute,
            seeds=cfg.seeds, founder=cfg.founder, kind='agent', admission=cfg.admission, data_dir=cfg.data_dir,
            ca_url=cfg.ca_url, token=cfg.token, pins=cfg.pins, connector=connector,
            require_https=cfg.require_https, region=cfg.region, labels=cfg.labels,
            gossip=gossip or GossipSettings(gossip_interval_ms=cfg.gossip_interval_ms), verify_keys=cfg.verify_keys,
            rules=self.rules, clock=clock, server_info={'name': 'sajhanet-agent', 'version': '1'},
            refresh_interval=max(5.0, cfg.catalog_refresh_seconds), vendor=cfg.vendor,
            rename=cfg.rename, max_hops=pol.max_hops, max_chain=pol.max_call_chain, audit=audit, **extra)
        p = self.participant
        self.identity.p = p
        if p.keys is not None:
            p.keys.own = lambda: own_key_bodies(self.policy())
        self._blocks_state = os.path.join(cfg.data_dir, 'blocks_state.json') if cfg.data_dir else ''
        self._blocks_version = (0, '')
        BlockPublication(p.node, lambda: (self.blocks_version(), list(self.policy().blocks))).install()
        from sajhanet_agent.home import Home
        self.home = Home(self)
        p.book.reexports = self.home.reexports
        p.node.tick_hooks.insert(0, self._reload)
        self._apply()

        def changed():
            self.catalog.invalidate()
            self.participant.invalidate()
        self.client.on_tools_changed = changed
        self.calls = 0

    # ── configuration ──────────────────────────────────────────────

    def policy(self):
        return self.policy_file.policy

    @property
    def importing(self) -> bool:
        """True when this agent pulls other members' catalogs: it is a home, or it re-exports."""
        return bool(self.cfg.home or self.policy().reexport)

    def _apply(self) -> None:
        """Bring the participant in line with the configuration (at start and after the file changed)."""
        p = self.participant
        pol = self.policy()
        node = p.node
        p.cfg.user_identity = list(pol.identity) if self.cfg.verify_keys else ['none']
        feats = node.extra_features
        for f, on in (('residency', True), ('reexport', pol.reexport),
                      ('token_exchange', self.cfg.verify_keys and 'token_exchange' in pol.identity)):
            if on and f not in feats:
                feats.append(f)
            elif not on and f in feats:
                feats.remove(f)
        if 'token_exchange' in feats:
            node.handlers[TOKEN_PATH] = self.identity.serve_token
        else:
            node.handlers.pop(TOKEN_PATH, None)
        p.book.reexport = bool(pol.reexport)
        p.host.max_hops = max(1, min(8, pol.max_hops))
        p.host.max_chain = max(1, min(32, pol.max_call_chain))
        self.rules.version += 1                            # the export view may change: a new catalog digest
        if self.home is not None:
            self.home.apply()

    def _reload(self) -> None:
        if self.policy_file.check():
            logger.info(f'the configuration file {self.cfg.config_path} changed; applied')
            self._apply()
            try:
                self.participant.invalidate()
                self.participant.node.refresh_record()
            except Exception as e:
                logger.debug(f'after the configuration changed: {e}')
        elif self.policy_file.error:
            logger.warning(f'the configuration file is not applied: {self.policy_file.error}')

    def blocks_version(self) -> int:
        """The version of this agent's blocks document: one more each time the blocks change (kept in the data
        directory, so it only grows)."""
        digest = hashlib.sha256(jcs.canonicalize([{k: v for k, v in b.items() if k != 'set_at'}
                                                  for b in self.policy().blocks])).hexdigest()
        version, held = self._blocks_version
        if held == digest:
            return version
        saved: Dict[str, Any] = {}
        if self._blocks_state:
            try:
                with open(self._blocks_state, 'r', encoding='utf-8') as f:
                    saved = json.load(f) or {}
            except (OSError, ValueError):
                saved = {}
        version = int(saved.get('version') or 0)
        if saved.get('digest') != digest and (version or self.policy().blocks):
            version += 1
            if self._blocks_state:
                try:
                    os.makedirs(os.path.dirname(os.path.abspath(self._blocks_state)), exist_ok=True)
                    with open(self._blocks_state, 'w', encoding='utf-8') as f:
                        json.dump({'version': version, 'digest': digest}, f)
                except OSError as e:
                    logger.warning(f'the blocks version is not saved: {e}')
        self._blocks_version = (version, digest)
        return version

    # ── tools ──────────────────────────────────────────────────────

    def local_names(self) -> List[str]:
        return [t['name'] for t in self.catalog.tools(self.cfg.net)]

    def _local_tool(self, name: str) -> Optional[Dict[str, Any]]:
        local = self.participant.book.local_name(name) or name
        return self.catalog.definition(local)

    def _classes(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """``data_classes`` for a tool's net metadata (protocol §10.2): its marks and the file's overlay."""
        oa, orr = self.policy().residency.marks([str(tool.get('name') or '')])
        out = {}
        for k, marks in (('arguments', R.merge_marks(R.schema_marks(tool.get('inputSchema')), oa)),
                         ('results', R.merge_marks(R.schema_marks(tool.get('outputSchema')), orr))):
            cs = sorted({c for v in marks.values() for c in v})
            if cs:
                out[k] = cs
        return {'data_classes': out} if out else {}

    def call_own(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """A local client's call of one of the fronted server's tools."""
        try:
            result = self.client.call_tool(name, arguments, timeout=self.cfg.call_timeout_seconds)
        except (MCPUnavailable, MCPError) as e:
            return {'content': [{'type': 'text', 'text': f'{name}: {getattr(e, "message", None) or e}'}],
                    'isError': True}
        out = {k: v for k, v in result.items() if k in ('content', 'structuredContent', 'isError', '_meta')}
        out.setdefault('content', [])
        return out

    # the host side of a forwarded call: the export policy has allowed it (§15.4 steps 1 to 9)
    def _execute(self, ctx: CallContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        if ctx.reexport is not None:                  # a tool this agent re-exports: relayed to its origin (§16)
            return self.home.relay(ctx, arguments)
        try:                                   # the server's own name for the tool (§5.5: ctx.tool is published)
            result = self.client.call_tool(ctx.local_tool or ctx.tool, arguments, timeout=self.cfg.call_timeout_seconds)
        except MCPUnavailable as e:
            if not e.sent:
                raise HostRefusal('unavailable', str(e), executed=False)
            return {'content': [{'type': 'text', 'text': f'{ctx.tool}: {e}'}], 'isError': True}
        except MCPError as e:
            return {'content': [{'type': 'text', 'text': f'{ctx.tool}: {e.message}'}], 'isError': True}
        out = {k: v for k, v in result.items() if k in ('content', 'structuredContent', 'isError', '_meta')}
        out.setdefault('content', [])
        return out

    def start(self) -> 'Agent':
        self.participant.start()
        return self

    def tick(self) -> None:
        self.participant.tick()

    def handle(self, method, path, query, headers, body, secure=True, source=''):
        return self.participant.handle(method, path, query, headers, body, secure=secure, source=source)

    def handle_client(self, method, path, headers, body):
        """One request from a local MCP client (the home's listener): ``(status, headers, body)``."""
        return self.home.handle_client(method, path, headers, body)

    def run_in_background(self):
        return self.participant.run_in_background()

    def stop(self, leave: bool = True) -> None:
        self.participant.stop(leave=leave)
        self.client.close()

    def status(self) -> Dict[str, Any]:
        out = self.participant.status()
        out['mcp'] = {'transport': 'stdio' if self.cfg.mcp_command else 'http' if self.cfg.mcp_url else 'in_process',
                      'error': self.catalog.error}
        pol = self.policy()
        out['config'] = {'path': self.cfg.config_path, 'error': self.policy_file.error, 'identity': list(pol.identity),
                         'users': len(pol.users), 'blocks': len(pol.blocks), 'residency_rules': len(pol.residency.rules),
                         'reexport': pol.reexport}
        out['home'] = {'on': bool(self.cfg.home), 'remote_tools': len(self.home.router.rows()) if self.importing else 0,
                       'reexported': [t['name'] for t in self.home.reexports(None)] if pol.reexport else []}
        return out


__all__ = ['Agent', 'AgentConfig', 'McpCatalog', 'make_client', 'CallableMCPClient']
