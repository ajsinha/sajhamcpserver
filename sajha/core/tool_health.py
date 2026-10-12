"""
SAJHA MCP Server — Tool Health & Execution Replay
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Tool Dependency Graph: groups the registry's tools by tool domain, with the providers their configs name
Health Dashboard: aggregates circuit breaker state per provider
Execution Replay: stores last N executions per tool for replay/debugging
"""
import hashlib
import json
import logging
import time
import threading
from collections import Counter, defaultdict, deque
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# TOOL DEPENDENCY GRAPH
# ═══════════════════════════════════════════════════════════════════

def _by_domain(tools_registry) -> Dict[str, List[str]]:
    """The registry's tool names grouped by tool domain key (``sajha/tools/domains.py``)."""
    from sajha.tools import domains as D
    groups: Dict[str, List[str]] = defaultdict(list)
    for name, tool in dict(getattr(tools_registry, 'tools', None) or {}).items():
        try:
            key = D.key_of_name(tools_registry, name, tool)
        except Exception:
            key = ''
        if key:
            groups[key].append(name)
    return groups


def build_dependency_graph(tools_registry) -> List[Dict]:
    """One entry per tool domain of the live registry (its tool folder, or a proxied server's prefix):
    the domain's label and key, how many tools it has, the providers its tool configs name
    (``metadata.provider``) and up to ten tool names. Derived, never restated: which providers exist and
    how many tools each has is whatever the registry serves."""
    from sajha.tools import domains as D
    tools = getattr(tools_registry, 'tools', None) or {}
    graph = []
    for key, names in _by_domain(tools_registry).items():
        sources: Counter = Counter()
        for name in names:
            meta = (getattr(tools.get(name), 'config', None) or {}).get('metadata') or {}
            if isinstance(meta, dict) and isinstance(meta.get('provider'), str) and meta['provider'].strip():
                sources[meta['provider'].strip()] += 1
        graph.append({
            'provider': D.domain_label(key),
            'prefix': key,                                   # the domain key (kept under its old name)
            'api_endpoint': ', '.join(p for p, _ in sources.most_common(3)),
            'registered_tools': len(names),
            'tools': sorted(names)[:10],                     # first 10 for display
        })
    return sorted(graph, key=lambda g: (-g['registered_tools'], g['provider']))


def get_provider_health(tools_registry) -> List[Dict]:
    """Get health status per provider combining circuit breaker state."""
    from sajha.core.circuit_breaker import get_circuit_registry
    graph = build_dependency_graph(tools_registry)
    registry = get_circuit_registry()
    worst = {'closed': 0, 'half_open': 1, 'open': 2}
    by_domain = _by_domain(tools_registry)
    for entry in graph:
        # the breakers of the domain's tools (one per provider prefix of circuit_breaker.py); the worst wins
        breakers = {}
        for name in by_domain.get(entry['prefix'], []):
            b = registry.get_breaker(name)
            if b is not None:
                breakers[id(b)] = b
        state, failures = 'closed', 0
        for b in breakers.values():
            failures += b.failure_count
            if worst.get(b.state.value, 0) > worst.get(state, 0):
                state = b.state.value
        entry['circuit_state'] = state
        entry['failure_count'] = failures
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
