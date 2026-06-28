"""
SAJHA MCP Server v5.1.0 — Circuit Breaker
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Prevents cascading failures when external APIs are down.
After N consecutive failures, the circuit opens and returns
cached results or a degraded error for M seconds.

States: CLOSED (normal) → OPEN (failing) → HALF_OPEN (probing)
"""
import logging
import threading
import time
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal — requests pass through
    OPEN = "open"           # Failing — requests short-circuited
    HALF_OPEN = "half_open" # Probing — one request allowed to test recovery


class CircuitBreaker:
    """Per-provider circuit breaker."""

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: int = 60, half_open_max: int = 1):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.last_state_change = time.time()
        self._lock = threading.Lock()

    def can_execute(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = time.time()
                    logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN (probing)")
                    return True
                return False
            if self.state == CircuitState.HALF_OPEN:
                return self.success_count < self.half_open_max
            return False

    def record_success(self):
        """Record a successful execution."""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.half_open_max:
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
                    self.last_state_change = time.time()
                    logger.info(f"Circuit {self.name}: HALF_OPEN → CLOSED (recovered)")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def record_failure(self):
        """Record a failed execution."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                self.success_count = 0
                self.last_state_change = time.time()
                logger.warning(f"Circuit {self.name}: HALF_OPEN → OPEN (probe failed)")
            elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.last_state_change = time.time()
                logger.warning(f"Circuit {self.name}: CLOSED → OPEN after {self.failure_count} failures")

    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'failure_threshold': self.failure_threshold,
            'recovery_timeout': self.recovery_timeout,
            'last_failure': self.last_failure_time,
            'last_state_change': self.last_state_change,
        }


class CircuitBreakerRegistry:
    """Registry of circuit breakers by provider."""

    # Provider → API mapping
    PROVIDER_MAP = {
        'fmp_': 'FMP (financialmodelingprep.com)',
        'yahoo_': 'Yahoo Finance',
        'alpha_': 'Alpha Vantage',
        'fred_': 'FRED (stlouisfed.org)',
        'openbb_': 'OpenBB',
        'coingecko_': 'CoinGecko',
        'edgar_': 'SEC EDGAR',
        'tavily_': 'Tavily Search',
        'google_': 'Google Search',
        'web_': 'Web Crawler',
        'wikipedia_': 'Wikipedia',
        'wb_': 'World Bank',
        'un_': 'United Nations',
        'fbi_': 'FBI Crime Data',
        'powerbi_': 'PowerBI',
        'sharepoint_': 'SharePoint',
    }

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()

    def get_breaker(self, tool_name: str) -> Optional[CircuitBreaker]:
        """Get or create circuit breaker for a tool's provider."""
        provider = self._get_provider(tool_name)
        if not provider:
            return None
        with self._lock:
            if provider not in self._breakers:
                self._breakers[provider] = CircuitBreaker(
                    name=self.PROVIDER_MAP.get(provider, provider),
                    failure_threshold=5,
                    recovery_timeout=60,
                )
            return self._breakers[provider]

    def _get_provider(self, tool_name: str) -> Optional[str]:
        for prefix in self.PROVIDER_MAP:
            if tool_name.startswith(prefix):
                return prefix
        return None

    def all_status(self) -> list:
        with self._lock:
            return [b.to_dict() for b in self._breakers.values()]


# Module singleton
_registry: Optional[CircuitBreakerRegistry] = None

def get_circuit_registry() -> CircuitBreakerRegistry:
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry
