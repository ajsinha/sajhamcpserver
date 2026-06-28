"""
SAJHA MCP Server v5.2.0 — Tool Health & Execution Replay
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Tool Dependency Graph: maps tools → providers → external APIs
Health Dashboard: aggregates circuit breaker state per provider
Execution Replay: stores last N executions per tool for replay/debugging
"""
import hashlib
import json
import logging
import time
import threading
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# TOOL DEPENDENCY GRAPH
# ═══════════════════════════════════════════════════════════════════

PROVIDER_DEPENDENCIES = {
    'fmp_': {'provider': 'FMP', 'api': 'https://financialmodelingprep.com/api', 'tools': 100},
    'openbb_': {'provider': 'OpenBB', 'api': 'OpenBB SDK (local)', 'tools': 70},
    'fred_': {'provider': 'FRED', 'api': 'https://api.stlouisfed.org', 'tools': 55},
    'yahoo_': {'provider': 'Yahoo Finance', 'api': 'https://query1.finance.yahoo.com', 'tools': 35},
    'alpha_': {'provider': 'Alpha Vantage', 'api': 'https://www.alphavantage.co/query', 'tools': 35},
    'coingecko_': {'provider': 'CoinGecko', 'api': 'https://api.coingecko.com/api/v3', 'tools': 25},
    'edgar_': {'provider': 'SEC EDGAR', 'api': 'https://efts.sec.gov', 'tools': 20},
    'calc_': {'provider': 'Calculators', 'api': 'Local (no external)', 'tools': 19},
    'wb_': {'provider': 'World Bank', 'api': 'https://api.worldbank.org/v2', 'tools': 10},
    'tavily_': {'provider': 'Tavily', 'api': 'https://api.tavily.com', 'tools': 8},
    'duckdb_': {'provider': 'DuckDB', 'api': 'Local (embedded DB)', 'tools': 6},
    'un_': {'provider': 'United Nations', 'api': 'https://data.un.org/ws', 'tools': 9},
    'fbi_': {'provider': 'FBI', 'api': 'https://api.usa.gov/crime', 'tools': 9},
    'msdoc_': {'provider': 'MS Document', 'api': 'Local (file processing)', 'tools': 10},
    'powerbi_': {'provider': 'PowerBI', 'api': 'https://api.powerbi.com', 'tools': 5},
    'sharepoint_': {'provider': 'SharePoint', 'api': 'SharePoint REST API', 'tools': 3},
    'livelink_': {'provider': 'LiveLink', 'api': 'OpenText LiveLink API', 'tools': 2},
}


def get_tool_provider(tool_name: str) -> Optional[Dict]:
    """Get provider info for a tool."""
    for prefix, info in PROVIDER_DEPENDENCIES.items():
        if tool_name.startswith(prefix):
            return {'prefix': prefix, **info}
    return None


def build_dependency_graph(tools_registry) -> List[Dict]:
    """Build the full dependency graph from the tools registry."""
    graph = []
    provider_tools = defaultdict(list)
    if tools_registry:
        for name in tools_registry.tools:
            for prefix in PROVIDER_DEPENDENCIES:
                if name.startswith(prefix):
                    provider_tools[prefix].append(name)
                    break

    for prefix, info in PROVIDER_DEPENDENCIES.items():
        tools = provider_tools.get(prefix, [])
        graph.append({
            'provider': info['provider'],
            'prefix': prefix,
            'api_endpoint': info['api'],
            'registered_tools': len(tools),
            'expected_tools': info['tools'],
            'is_local': 'Local' in info['api'],
            'tools': sorted(tools)[:10],  # First 10 for display
        })
    return sorted(graph, key=lambda g: -g['registered_tools'])


def get_provider_health(tools_registry) -> List[Dict]:
    """Get health status per provider combining circuit breaker state."""
    from sajha.core.circuit_breaker import get_circuit_registry
    graph = build_dependency_graph(tools_registry)
    registry = get_circuit_registry()
    for entry in graph:
        breaker = registry.get_breaker(entry['prefix'] + 'test')
        if breaker:
            entry['circuit_state'] = breaker.state.value
            entry['failure_count'] = breaker.failure_count
        else:
            entry['circuit_state'] = 'closed'
            entry['failure_count'] = 0
        entry['status'] = 'healthy' if entry['circuit_state'] == 'closed' else (
            'degraded' if entry['circuit_state'] == 'half_open' else 'down')
    return graph


# ═══════════════════════════════════════════════════════════════════
# EXECUTION REPLAY
# ═══════════════════════════════════════════════════════════════════

class ExecutionReplayStore:
    """
    Stores the last N executions per tool for replay and debugging.

    Each entry: {tool_name, arguments, result, duration_ms, timestamp, user_id, success}
    """

    def __init__(self, max_per_tool: int = 20, max_total: int = 5000):
        self._store: Dict[str, deque] = defaultdict(lambda: deque(maxlen=max_per_tool))
        self._max_total = max_total
        self._total_count = 0
        self._lock = threading.Lock()

    def record(self, tool_name: str, arguments: Dict, result: Any,
               duration_ms: float, user_id: str = None, success: bool = True):
        """Record a tool execution for replay."""
        # Hash arguments for dedup display (don't store raw if sensitive)
        args_hash = hashlib.md5(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()[:8]
        entry = {
            'id': f"{tool_name}:{args_hash}:{int(time.time()*1000)}",
            'tool_name': tool_name,
            'arguments': arguments,
            'result_preview': self._preview(result),
            'result_size': len(json.dumps(result, default=str)) if result else 0,
            'duration_ms': round(duration_ms, 1),
            'timestamp': time.time(),
            'user_id': user_id,
            'success': success,
        }
        with self._lock:
            self._store[tool_name].append(entry)
            self._total_count += 1

    def get_history(self, tool_name: str) -> List[Dict]:
        """Get execution history for a tool (most recent first)."""
        with self._lock:
            return list(reversed(self._store.get(tool_name, [])))

    def get_recent(self, limit: int = 50) -> List[Dict]:
        """Get most recent executions across all tools."""
        with self._lock:
            all_entries = []
            for entries in self._store.values():
                all_entries.extend(entries)
            all_entries.sort(key=lambda e: e['timestamp'], reverse=True)
            return all_entries[:limit]

    def get_entry(self, entry_id: str) -> Optional[Dict]:
        """Get a specific execution entry by ID."""
        with self._lock:
            for entries in self._store.values():
                for e in entries:
                    if e['id'] == entry_id:
                        return e
        return None

    def stats(self) -> Dict:
        with self._lock:
            tools_tracked = len(self._store)
            total_entries = sum(len(d) for d in self._store.values())
            return {
                'tools_tracked': tools_tracked,
                'total_entries': total_entries,
                'total_recorded': self._total_count,
            }

    @staticmethod
    def _preview(result: Any, max_len: int = 200) -> str:
        """Create a short preview of the result."""
        try:
            s = json.dumps(result, default=str)
            return s[:max_len] + ('...' if len(s) > max_len else '')
        except Exception:
            return str(result)[:max_len]


# Module singleton
_replay: Optional[ExecutionReplayStore] = None

def get_replay_store() -> ExecutionReplayStore:
    global _replay
    if _replay is None:
        _replay = ExecutionReplayStore()
    return _replay
