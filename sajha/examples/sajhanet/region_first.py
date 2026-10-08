"""
An example third-party SAJHA Net plug-in: the routing strategy ``region_first``.

Within one net, the hosts of a tool are tried local first, then hosts in this server's region,
then the rest, each group by measured latency and then instance name; the tool's preferences
(``sajhanet.preferences``) come first of all, as every routing strategy must (its contract check).

Load it at start by naming the module in ``sajhanet.plugins.modules`` and select it with
``sajhanet.plugins.routing: region_first``:

    sajhanet:
      region: eu-west
      plugins:
        modules: [sajha.examples.sajhanet.region_first]
        routing: region_first

A package can register the same class through the entry-point group ``sajha.net.plugins`` instead
(entry-point name ``routing.region_first``, value ``my_package.module:RegionFirst``).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import os

from sajha.net import plugins


@plugins.register('routing')
class RegionFirst(plugins.RoutingStrategy):
    name = 'region_first'

    def __init__(self, region: str = ''):
        self.region = region or os.environ.get('SAJHA_SAJHANET_REGION', '')

    def order(self, tool, hosts, preferred=None):
        def key(h):
            same = bool(self.region) and str((h.attrs or {}).get('region') or '') == self.region
            return (not h.local, not same, h.latency_ms is None, h.latency_ms or 0, h.instance)
        base = sorted(hosts, key=key)
        if not preferred:
            return base
        rank = {p: i for i, p in enumerate(preferred)}
        first = sorted([h for h in base if h.instance in rank], key=lambda h: rank[h.instance])
        return first + [h for h in base if h.instance not in rank]
