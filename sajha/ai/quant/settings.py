"""
SAJHA MCP Server — ``ai.quant.*``: the quantitative workspace's settings (Quantitative Planners §5).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every key resolves env > YAML > default, like ``ai.planners.*``; the env names are
``SAJHA_AI_QUANT_<FIELD>`` and ``SAJHA_AI_QUANT_CODE_ACT_<FIELD>``. The default of the reserved
planner setting ``numbers_check`` is ``ai.planners.numbers_check`` (sajha/ai/planners_engine/settings.py).
Docs: docs/getting-started/Configuration Reference.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sajha.ai.llm.settings import Layered, load_ai_yaml, resolve_layers

logger = logging.getLogger(__name__)


class QuantCodeActSettings(Layered):
    roles: List[str] = []                  # roles that may run a planner using code_act; none by default


class QuantTopSettings(Layered):
    max_graph_nodes: int = 40              # nodes in one computation graph (calc_graph)
    max_table_cells: int = 10000           # cells in one table quantity
    day_count: str = "act/365"             # the basis for days <-> years


@dataclass
class QuantSettings:
    max_graph_nodes: int = 40
    max_table_cells: int = 10000
    day_count: str = "act/365"
    code_act: QuantCodeActSettings = field(default_factory=QuantCodeActSettings)


def _resolve(cls, section: str, raw: Dict[str, Any], environ=None):
    cfg = {k: v for k, v in dict(raw or {}).items() if k in cls.model_fields}
    try:
        model, _ = resolve_layers(cls, section, cfg, environ=environ)
        return model
    except Exception as e:
        logger.warning(f"ai.{section.replace('_', '.')}: {e}; using the defaults")
        return cls()


def load_settings(raw: Optional[Dict[str, Any]] = None, environ=None) -> QuantSettings:
    if raw is None:
        raw = load_ai_yaml().get("quant") or {}
    raw = dict(raw or {})
    top = _resolve(QuantTopSettings, "quant", raw, environ)
    from sajha.ai.quant.units import DAY_COUNTS
    if top.day_count.lower().replace(" ", "") not in DAY_COUNTS:
        logger.warning(f"ai.quant.day_count {top.day_count!r} is not one of {', '.join(DAY_COUNTS)}; using act/365")
        top = top.model_copy(update={"day_count": "act/365"})
    return QuantSettings(**top.model_dump(),
                         code_act=_resolve(QuantCodeActSettings, "quant_code_act", raw.get("code_act") or {}, environ))


_settings: Optional[QuantSettings] = None


def quant_settings() -> QuantSettings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_quant_settings(s: Optional[QuantSettings]) -> None:
    """Install settings (tests); None re-reads them on next use."""
    global _settings
    _settings = s
