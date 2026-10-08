"""The Ask SAJHA tool-search index follows every change to the tool registry, whatever made it
(Studio creators, composites, federation, API import, the file watcher): ToolsRegistry calls its
change listeners on each register/unregister/enable/disable, once per bulk(), and the resolver
listens. Before, only a full reload (or a path that remembered to call _notify_reload) re-synced it."""

import gc
import logging
import threading
import time

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.ai.tool_resolver import ToolResolver
from tests.ai.conftest import FakeTool, make_gateway


def bare_registry():
    from sajha.tools.tools_registry import ToolsRegistry
    reg = object.__new__(ToolsRegistry)
    reg.tools, reg.tool_configs, reg.tool_errors = {}, {}, {}
    reg._tools_lock, reg.builtin_tools, reg.logger = threading.RLock(), {}, logging.getLogger('t')
    reg._properties_configurator = None
    reg._file_timestamps = {}
    return reg


def zebra():
    return FakeTool("zebra_stripe_count", "Count the stripes on a zebra", output={"stripes": 42})


def test_registry_notifies_change_listeners_coalesced_by_bulk():
    reg = bare_registry()
    seen = []
    reg.add_change_listener(lambda: seen.append(1))
    reg.register_tool(zebra())
    assert seen == [1]
    reg.register_tool(zebra())                         # the same definition again: no change
    assert seen == [1]
    with reg.bulk():
        for i in range(5):
            reg.register_tool(FakeTool(f"t_{i}", f"tool {i}"))
        reg.unregister_tool("t_0")
    assert seen == [1, 1]                              # one notification for the whole bulk
    with reg.bulk():
        reg.register_tool(FakeTool("tmp", "x"))
        reg.unregister_tool("tmp")
    assert seen == [1, 1]                              # ended where it started: nothing to announce
    reg.unregister_tool("zebra_stripe_count")
    assert seen == [1, 1, 1]


def test_listeners_are_held_weakly():
    reg = bare_registry()

    class Owner:
        n = 0

        def hit(self):
            Owner.n += 1

    o = Owner()
    reg.add_change_listener(o.hit)
    reg.register_tool(FakeTool("a", "a"))
    del o
    gc.collect()
    reg.register_tool(FakeTool("b", "b"))
    assert Owner.n == 1 and reg._change_listeners == []


def test_a_hot_loaded_tool_is_shortlisted_without_a_reload():
    reg = bare_registry()
    svc = IntelligenceService(make_gateway(), reg, settings=AskSettings(audit=False))
    q = "How many stripes does a zebra have? Count the stripes."
    assert "zebra_stripe_count" not in svc.ask(q, RequestContext(user_id="u")).shortlist
    reg.register_tool(zebra())                         # e.g. a Studio creator saving a new tool
    r = svc.ask(q, RequestContext(user_id="u"))
    assert "zebra_stripe_count" in r.shortlist and r.steps[0].name == "zebra_stripe_count"
    reg.unregister_tool("zebra_stripe_count")
    assert "zebra_stripe_count" not in svc.ask(q, RequestContext(user_id="u")).shortlist


def test_composite_and_federation_paths_reach_the_index():
    """Paths that register through register_tool inside bulk() (composites, federation sync,
    API import) are covered by the same listener."""
    reg = bare_registry()
    resolver = ToolResolver(None, reg, persist=False)
    resolver.refresh_lexical()
    with reg.bulk():                                  # what CompositeToolEngine.load_from_db does
        reg.register_tool(FakeTool("acme_composite_report", "Composite report of acme sales and margins"))
        fed = FakeTool("upstream__weather_now", "Federated: current weather for a city")
        fed.namespaced_name = True                    # a federated tool's <prefix>__<tool> (sajha/tools/naming.py)
        reg.register_tool(fed)
    names = [m.tool_name for m in resolver.resolve("acme sales margins composite report", top_k=3)]
    assert names[0] == "acme_composite_report"
    assert resolver.resolve("current weather city", top_k=1)[0].tool_name == "upstream__weather_now"


def test_the_vector_tier_resyncs_in_the_background_and_bm25_serves_meanwhile():
    import pytest
    pytest.importorskip("numpy")                       # the vector tier of tool search uses numpy
    from sajha.ai.embedders import GatewayEmbedder
    reg = bare_registry()
    reg.register_tool(FakeTool("calc_alpha", "alpha calculator"))
    gw = make_gateway()
    resolver = ToolResolver(GatewayEmbedder(gw), reg, persist=False)
    resolver.build_index()
    assert resolver.stats()["mode"] == "vector"
    reg.register_tool(zebra())
    assert resolver.resolve("zebra stripes", top_k=1)[0].tool_name == "zebra_stripe_count"   # BM25 meanwhile
    for _ in range(100):
        if not resolver._vector_stale and not resolver._sync_running:
            break
        time.sleep(0.02)
    assert resolver.index.stats()["indexed_tools"] == 2 and not resolver._vector_stale
