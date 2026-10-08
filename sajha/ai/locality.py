"""
SAJHA MCP Server — where an offered tool runs, for planners' shortlists (locality-aware ranking).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A planner (Ask SAJHA, an LLM tool in answer mode) sees this server's own tools, SAJHA Net proxies
(``<net>__<instance>__<tool>`` and their plain aliases) and federated tools in one shortlist. This
module says where each one runs and nudges the ranking (docs/architecture/SAJHA Net.md §13):

* **local** tools (this server's own) rank first; then **remote** SAJHA Net tools, nearer and
  cheaper hosts first: a host named in ``sajhanet.preferences`` for the tool, the same region as this
  server in that net, a healthy host, a lower indicative latency; **federated** tools rank like a
  remote tool with nothing known about it.
* The nudges are small (a few hundredths of the resolver's 0-1 score), so a remote tool is still
  offered when it is the right tool, not dropped because a local one ranked near it.
* Tools whose host is unavailable (``state`` other than active) or reports itself down are left out.
* Every entry records ``locality`` with a ``why`` in words, shown in the ``shortlist`` event.

A **locality restriction** narrows the shortlist before ranking: ``any`` (default), ``local`` (only
this server's own tools) or ``net:<name>`` (this server's own tools and that net's remote tools). The
restriction comes from the ask (``locality=``), else the planner's ``settings.locality``, else
``ai.ask.locality``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EXT = "io.sajha/net"
REMOTE_PENALTY = 0.02           # a remote (or federated) tool, before anything else is known
OTHER_REGION_PENALTY = 0.02     # a remote host in another region than this server (both known)
DEGRADED_PENALTY = 0.05
LATENCY_PENALTY_MAX = 0.03      # 1 hundredth per 100 ms of indicative latency, at most this
PREFERENCE_BONUS = 0.015        # a host named in sajhanet.preferences for the tool (first entry most)
DOWN = ("down", "unhealthy", "unavailable")


class LocalityError(ValueError):
    pass


def parse(spec: Any) -> Tuple[str, str]:
    """``any`` | ``local`` | ``net:<name>`` → (kind, net). Raises :class:`LocalityError` on anything else."""
    s = str(spec or "any").strip()
    low = s.lower()
    if low in ("", "any", "all"):
        return "any", ""
    if low == "local":
        return "local", ""
    if low.startswith("net:") and s[4:].strip():
        return "net", s[4:].strip()
    raise LocalityError(f'locality must be any, local or net:<name>, not "{s}"')


def describe(tool: Any) -> Dict[str, Any]:
    """Where ``tool`` runs: ``where`` (local | remote | federated) and, for a remote tool, its net, host,
    region, health, state and indicative latency (from the proxy's net metadata)."""
    meta = getattr(tool, "meta", None)
    if isinstance(meta, dict) and meta.get("locality") == "remote":
        out = {"where": "remote", "net": str(meta.get("net") or ""), "instance": str(meta.get("instance") or ""),
               "qualified_name": str(meta.get("qualified_name") or ""), "host_tool": str(meta.get("host_tool") or "")}
        for k in ("region", "health", "state", "latency_ms_p50", "llm_tool"):
            if meta.get(k) not in (None, ""):
                out[k] = meta[k]
        return out
    try:
        from sajha.federation.tool import FederatedTool
        if isinstance(tool, FederatedTool):
            return {"where": "federated"}
    except Exception:
        pass
    return {"where": "local"}


def allowed(info: Dict[str, Any], kind: str, net: str = "") -> bool:
    if kind == "any":
        return True
    if info["where"] == "local":
        return True
    return kind == "net" and info["where"] == "remote" and info.get("net") == net


def _net_context() -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """This server's region per net, and ``sajhanet.preferences`` (empty when SAJHA Net is off)."""
    try:
        from sajha.net.integration.catalogs import get_catalogs
        cats = get_catalogs()
    except Exception:
        cats = None
    if cats is None:
        return {}, {}
    regions = {}
    for net, book in dict(getattr(cats, "books", {}) or {}).items():
        try:
            regions[net] = str(book.node.cfg.region or "")
        except Exception:
            regions[net] = ""
    prefs = dict(getattr(getattr(cats, "settings", None), "preferences", {}) or {})
    return regions, prefs


def _nudge(info: Dict[str, Any], regions: Dict[str, str], prefs: Dict[str, List[str]]) -> Tuple[float, List[str]]:
    """(score adjustment, reasons in words) for one tool."""
    where = info["where"]
    if where == "local":
        return 0.0, ["runs on this server"]
    if where == "federated":
        return -REMOTE_PENALTY, ["runs on a federated MCP server"]
    adj, why = -REMOTE_PENALTY, [f"runs on {info.get('instance')} in {info.get('net')}"]
    part = info.get("host_tool") or ""
    pref = prefs.get(part) or []
    for i, p in enumerate(pref):
        pnet, _, phost = str(p).partition("/")
        if pnet == info.get("net") and (not phost or phost == info.get("instance")):
            adj += PREFERENCE_BONUS / (i + 1)
            why.append(f"preference {i + 1}")
            break
    mine, theirs = regions.get(info.get("net") or "", ""), str(info.get("region") or "")
    if mine and theirs:
        if mine == theirs:
            why.append(f"same region ({theirs})")
        else:
            adj -= OTHER_REGION_PENALTY
            why.append(f"another region ({theirs}; this server {mine})")
    if str(info.get("health") or "").lower() == "degraded":
        adj -= DEGRADED_PENALTY
        why.append("degraded")
    lat = info.get("latency_ms_p50")
    if isinstance(lat, (int, float)) and lat >= 0:
        adj -= min(LATENCY_PENALTY_MAX, float(lat) / 10000.0)
        why.append(f"about {int(lat)} ms")
    return adj, why


def rank(items: List[Dict[str, Any]], kind: str = "any", net: str = "") -> List[Dict[str, Any]]:
    """Filter ``items`` (shortlist entries with ``name``, ``score`` and ``tool``) by the restriction,
    leave out unavailable hosts, rank by locality, and record ``locality`` on each entry."""
    regions, prefs = _net_context()
    kept: List[Tuple[float, int, Dict[str, Any]]] = []
    wheres = set()
    for i, it in enumerate(items):
        info = describe(it.get("tool"))
        if not allowed(info, kind, net):
            continue
        if info["where"] == "remote" and (str(info.get("state") or "active") != "active"
                                          or str(info.get("health") or "").lower() in DOWN):
            continue
        adj, why = _nudge(info, regions, prefs)
        loc = {k: v for k, v in info.items() if k in ("where", "net", "instance", "region", "latency_ms_p50",
                                                      "health", "llm_tool")}
        loc["why"] = "; ".join(why)
        it = dict(it, locality=loc)
        wheres.add(info["where"])
        kept.append((float(it.get("score") or 0.0) + adj, i, it))
    if len(wheres) > 1:                       # only a mixed shortlist is re-ordered
        kept.sort(key=lambda x: (-x[0], x[1]))
    return [it for _s, _i, it in kept]


def resolve_spec(explicit: Any, planner_settings: Optional[Dict[str, Any]], default: Any) -> Tuple[str, str, str]:
    """(kind, net, source) from the ask's own choice, the planner's settings, then ``ai.ask.locality``."""
    for value, source in ((explicit, "ask"), ((planner_settings or {}).get("locality"), "planner"),
                          (default, "ai.ask.locality")):
        if value not in (None, ""):
            kind, net = parse(value)
            return kind, net, source
    return "any", "", "default"
