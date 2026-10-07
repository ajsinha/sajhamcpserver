"""
SAJHA MCP Server — ``ai.planners.*``: the planner registry's settings and graph ceilings.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Every key resolves env > YAML > default; the env names are ``SAJHA_AI_PLANNERS_<FIELD>`` and
``SAJHA_AI_PLANNERS_LIMITS_<FIELD>``. Docs: docs/getting-started/Configuration Reference.md and
docs/architecture/Planner Reference.md §11.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from sajha.ai.llm.settings import Layered, load_ai_yaml, resolve_layers

logger = logging.getLogger(__name__)


class PlannerLimitSettings(Layered):
    """``ai.planners.limits``: ceilings on a planner graph's shape (Planner Reference §11)."""
    max_stages_run: int = 40
    max_visits_per_edge: int = 10
    max_subplanner_depth: int = 2
    max_parallel: int = 4
    max_samples: int = 5
    max_foreach_items: int = 50


class PlannerTopSettings(Layered):
    dir: str = "config/planners"           # planner files, read through the storage backend
    default: str = "react"                 # an LLM tool's planner when it names none
    reload_interval_s: float = 2.0         # how often a lookup checks the files for changes
    python_builtins: bool = False          # true: react, plan_execute, recipes, router run the Python classes
    resume_ttl_s: int = 900                # how long a run paused at ask_user (MRTR) can be resumed
    dry_run_model: str = "mock/mock-planner"
    max_input_chars: int = 20000
    menu_min_pass_rate: float = 0.5        # a menu candidate whose latest eval run passed less is dropped


@dataclass
class PlannerSettings:
    dir: str = "config/planners"
    default: str = "react"
    reload_interval_s: float = 2.0
    python_builtins: bool = False
    resume_ttl_s: int = 900
    dry_run_model: str = "mock/mock-planner"
    max_input_chars: int = 20000
    menu_min_pass_rate: float = 0.5        # a menu candidate whose latest eval run passed less is dropped
    limits: PlannerLimitSettings = field(default_factory=PlannerLimitSettings)

    def ceilings(self):
        from sajha.ai.planners_engine.model import Ceilings
        c = Ceilings(**self.limits.model_dump())
        try:
            from sajha.ai.llm_tools.config import settings as llm_settings
            lim = llm_settings().limits
            c.max_steps, c.max_tool_calls, c.timeout_s = lim.max_steps, lim.max_tool_calls, lim.timeout_s
            c.max_cost_usd, c.max_output_tokens = lim.max_cost_usd, lim.max_output_tokens
        except Exception:
            pass
        return c


def _resolve(cls, section: str, raw: Dict[str, Any], environ=None):
    cfg = {k: v for k, v in dict(raw or {}).items() if k in cls.model_fields}
    try:
        model, _ = resolve_layers(cls, section, cfg, environ=environ)
        return model
    except Exception as e:
        logger.warning(f"ai.{section.replace('_', '.')}: {e}; using the defaults")
        return cls()


def load_settings(raw: Optional[Dict[str, Any]] = None, environ=None) -> PlannerSettings:
    if raw is None:
        raw = load_ai_yaml().get("planners") or {}
    raw = dict(raw or {})
    top = _resolve(PlannerTopSettings, "planners", raw, environ)
    return PlannerSettings(**top.model_dump(),
                           limits=_resolve(PlannerLimitSettings, "planners_limits", raw.get("limits") or {}, environ))


_settings: Optional[PlannerSettings] = None


def planner_settings() -> PlannerSettings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_planner_settings(s: Optional[PlannerSettings]) -> None:
    """Install settings (tests); None re-reads them on next use."""
    global _settings
    _settings = s
