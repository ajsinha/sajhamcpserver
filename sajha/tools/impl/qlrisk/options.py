# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The work bounds every qlrisk tool enforces.

Each bound is the configuration key ``qlrisk.<bound>`` (``qlrisk.max_mc_paths`` ..., so also the
environment variable ``SAJHA_QLRISK_MAX_MC_PATHS``), and a tool config may override it for that one
tool with a ``"bounds": {"max_mc_paths": 5000}`` object. A request above a bound is rejected with a
message naming the bound, never silently truncated.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Limits:
    max_trades: int = 200                 # trades in one request
    max_mc_paths: int = 20_000            # Monte Carlo paths / scenarios / simulations
    max_time_steps: int = 1_000           # time steps of a simulated path
    max_history_days: int = 2_500         # observations of a factor history (synthetic or supplied)
    max_drc_simulations: int = 200_000    # IMA DRC copula simulations
    max_cross_gamma_factors: int = 8      # factors in a cross-gamma request (4 repricings per pair)
    max_text_chars: int = 20_000          # JSON echoed in the text block (structuredContent is never cut)

    @classmethod
    def from_config(cls, overrides: Optional[Dict[str, Any]] = None) -> "Limits":
        """``qlrisk.<bound>`` from the SAJHA configuration, then ``overrides`` (a tool config's ``bounds``)."""
        from sajha.core.config import _get
        values = {}
        for f in fields(cls):
            raw = _get(f"qlrisk.{f.name}", "")
            if raw not in (None, ""):
                values[f.name] = int(float(raw))
        names = {f.name for f in fields(cls)}
        unknown = sorted(set(overrides or {}) - names)
        if unknown:
            raise ValueError(f"unknown qlrisk bound(s) {unknown}; bounds are {sorted(names)}")
        values.update({k: int(v) for k, v in (overrides or {}).items() if v is not None})
        for k, v in values.items():
            if v <= 0:
                raise ValueError(f"qlrisk bound {k} must be positive, got {v}")
        return cls(**values)

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}
