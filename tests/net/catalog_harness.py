# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
A SAJHA Net test net with catalogs and calls: :class:`tests.net.harness.TestNet` participants, each with
a :class:`~sajha.net.catalog.CatalogBook` over a static tool list, a :class:`~sajha.net.routing.HostServer`
on its MCP endpoint and a :class:`~sajha.net.routing.Router`. Every host's tool answers with
``<host>:<tool>`` and records the call.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from sajha.net.catalog import CatalogBook
from sajha.net.node import empty_404
from sajha.net.plugins import CatalogSource
from sajha.net.routing import CallContext, HostRefusal, HostServer, PeerSettings, Router
from tests.net.harness import TestNet


def tool(name: str, *, props: Optional[Dict[str, Any]] = None, annotations: Optional[Dict[str, Any]] = None,
         description: str = '', output: Optional[Dict[str, Any]] = None, **extra) -> Dict[str, Any]:
    t = {'name': name, 'description': description or f'{name} tool',
         'inputSchema': {'type': 'object', 'properties': props if props is not None else {'x': {'type': 'integer'}}}}
    if annotations is not None:
        t['annotations'] = annotations
    if output is not None:
        t['outputSchema'] = output
    t.update(extra)
    return t


class ListSource(CatalogSource):
    name = 'list'

    def __init__(self, tools: List[Dict[str, Any]]):
        self.items = tools

    def tools(self, net, peer=None):
        return copy.deepcopy(self.items)


class Site:
    """One participant: node, book, host server, router, its tools and the calls it served."""

    def __init__(self, net: TestNet, name: str, tools: List[Dict[str, Any]], **add_kw):
        self.name = name
        self.net = net
        self.node = net.add(name, **add_kw)
        self.source = ListSource(tools)
        self.book = CatalogBook(self.node, self.source, refresh_interval=300).attach()
        self.book.start()
        self.served: List[Dict[str, Any]] = []
        self.refuse: Optional[HostRefusal] = None
        self.host = HostServer(self.book, execute=self._execute, max_hops=2).attach()
        self.router = Router([self.book], local_tools=lambda: [t['name'] for t in self.source.items],
                             clock=net.clock, peer=PeerSettings(timeout_seconds=5), audit=self._audit)
        self.audits: List[tuple] = []
        p = net.participants[name]

        def route(method, path, query, headers, body, secure, p=p):
            if path == '/mcp':
                return p.handle_mcp(method, path, query, headers, body, secure=secure) or empty_404()
            return p.handle(method, path, query, headers, body, secure=secure, source='127.0.0.1')
        net.connector.routes[net.url(name)] = route
        self.node.refresh_record()

    def _audit(self, what, details):
        self.audits.append((what, details))

    def _execute(self, ctx: CallContext, arguments):
        if self.refuse is not None:
            raise self.refuse
        self.served.append({'tool': ctx.tool, 'arguments': arguments, 'peer': ctx.peer, 'trace_id': ctx.trace_id,
                            'attempt': ctx.attempt, 'hop': ctx.hop})
        return {'content': [{'type': 'text', 'text': f'{self.name}:{ctx.tool}'}]}

    def set_tools(self, tools: List[Dict[str, Any]]) -> None:
        self.source.items = tools
        self.book.invalidate()


class CatalogNet:
    """Sites joined into one net through the first site (the founder)."""

    def __init__(self, tmp, specs: Dict[str, List[Dict[str, Any]]], net: str = 'acme-net', base: Optional[TestNet] = None):
        self.n = base or TestNet(tmp, net=net)
        self.sites: Dict[str, Site] = {}
        first = None
        for name, tools in specs.items():
            if first is None:
                self.sites[name] = Site(self.n, name, tools, founder=True)
                first = name
            else:
                self.sites[name] = Site(self.n, name, tools, seeds=[self.n.url(first)])
        self.settle()

    def __getitem__(self, name: str) -> Site:
        return self.sites[name]

    def tick(self, rounds: int = 1, step: float = 1.0, only=None) -> None:
        for _ in range(rounds):
            for name, s in self.sites.items():
                if only is not None and name not in only:
                    continue
                if self.n.url(name) in self.n.connector.down:
                    continue
                s.node.tick()                          # runs the book's tick as a tick hook
            self.n.clock.advance(step)

    def settle(self, rounds: int = 6) -> None:
        self.tick(rounds)

    def live(self, observer: str) -> Dict[str, List[str]]:
        return {p: sorted(t['name'] for t in h.get('tools') or [])
                for p, h in self.sites[observer].book.live_peers().items()}

    def listed(self, observer: str) -> Dict[str, str]:
        return {r['qualified_name']: r['state'] for r in self.sites[observer].router.rows()}
