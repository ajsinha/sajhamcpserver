"""
The SAJHA Net agent: any MCP server as a full SAJHA Net participant (design §5.1, kind ``agent``).

The agent is the reference library (:mod:`sajha.net.library`) in front of one MCP server: it holds
the participant's identity (a self-signed certificate under ``admission: open`` or manual mode, or a
certificate from the net's CA through enrollment), gossips, publishes the server's ``tools/list`` as
its catalog with net metadata, verifies forwarded API keys against the net key directory, applies
its export policy, and passes allowed calls to the server.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from sajha.net.library import CallContext, ExportPolicy, HostRefusal, NetParticipant
from sajha.net.models import GossipSettings
from sajha.net.plugins import CatalogSource

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


class McpCatalog(CatalogSource):
    """The fronted server's ``tools/list``, cached; on failure the last good list is kept."""
    name = 'mcp_tools_list'

    def __init__(self, client: MCPClient, refresh_seconds: float = 60.0, clock: Callable[[], float] = time.time):
        self.client = client
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
            return [dict(t) for t in self._tools]


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
                 clock: Callable[[], float] = time.time, gossip: Optional[GossipSettings] = None, kv=None):
        self.cfg = cfg
        self.client = client or make_client(cfg)
        self.catalog = McpCatalog(self.client, cfg.catalog_refresh_seconds, clock)
        rules = ExportPolicy(tools=cfg.export_tools, peers=cfg.export_peers, roles=cfg.export_roles,
                             service_calls=cfg.service_calls, host=cfg.instance)
        extra = {'kv': kv} if kv is not None else {}
        self.participant = NetParticipant.build(
            net=cfg.net, instance=cfg.instance, base_url=cfg.url, source=self.catalog, execute=self._execute,
            seeds=cfg.seeds, founder=cfg.founder, kind='agent', admission=cfg.admission, data_dir=cfg.data_dir,
            ca_url=cfg.ca_url, token=cfg.token, pins=cfg.pins, connector=connector,
            require_https=cfg.require_https, region=cfg.region, labels=cfg.labels,
            gossip=gossip or GossipSettings(gossip_interval_ms=cfg.gossip_interval_ms), verify_keys=cfg.verify_keys,
            rules=rules, clock=clock, server_info={'name': 'sajhanet-agent', 'version': '1'},
            refresh_interval=max(5.0, cfg.catalog_refresh_seconds), **extra)

        def changed():
            self.catalog.invalidate()
            self.participant.invalidate()
        self.client.on_tools_changed = changed
        self.calls = 0

    # the host side of a forwarded call: the export policy has allowed it (§15.4 steps 1 to 9)
    def _execute(self, ctx: CallContext, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        try:
            result = self.client.call_tool(ctx.tool, arguments, timeout=self.cfg.call_timeout_seconds)
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

    def run_in_background(self):
        return self.participant.run_in_background()

    def stop(self, leave: bool = True) -> None:
        self.participant.stop(leave=leave)
        self.client.close()

    def status(self) -> Dict[str, Any]:
        out = self.participant.status()
        out['mcp'] = {'transport': 'stdio' if self.cfg.mcp_command else 'http' if self.cfg.mcp_url else 'in_process',
                      'error': self.catalog.error}
        return out


__all__ = ['Agent', 'AgentConfig', 'McpCatalog', 'make_client', 'CallableMCPClient']
