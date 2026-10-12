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
from typing import Any, Dict, List, Optional

from pydantic import field_validator

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


class PlannerLearningSettings(Layered):
    """``ai.planners.learning``: planners chosen by learning from results (LLM Tools §9.13,
    Planner Reference §6.6.2). Env ``SAJHA_AI_PLANNERS_LEARNING_<FIELD>``."""
    dir: str = "data/planner_routing"      # proposals, approved versions and the active pointer
    rules: bool = True                     # approved routing rules take effect (false: ignored)
    min_samples: int = 5                   # outcomes a planner needs in a class before it is ranked
    cost_weight: float = 0.0               # score = quality - cost_weight * mean cost (USD) - ...
    latency_weight: float = 0.0            # ... - latency_weight * mean latency (seconds)
    window_days: float = 30                # evidence older than this is ignored
    max_records: int = 5000                # audit records read per learning run
    max_eval_runs: int = 200               # saved eval runs read per learning run
    reload_interval_s: float = 2.0         # how often the active rules are re-read
    bandit: bool = False                   # the online bandit (opt-in)
    bandit_algorithm: str = "thompson"     # thompson | ucb
    bandit_exploration: float = 0.1        # the most choices that may explore (0 to 0.5)
    bandit_min_samples: int = 5            # outcomes an arm needs before the bandit exploits it
    bandit_window_s: float = 3600          # the window the exploration share is counted over
    bandit_tools: List[str] = []           # empty: every tool with a planner menu; else only these
    bandit_seed: Optional[int] = None      # set: the bandit's random choices are reproducible
    bandit_guard_min_runs: int = 20        # explored outcomes before the guard judges them
    bandit_guard_min_success: float = 0.3  # explored success below this stops the bandit

    @field_validator("bandit_algorithm")
    @classmethod
    def _algorithm(cls, v):
        if v not in ("thompson", "ucb"):
            raise ValueError(f"bandit_algorithm {v!r} is not one of thompson, ucb")
        return v

    @field_validator("bandit_exploration")
    @classmethod
    def _exploration(cls, v):
        if not 0 <= float(v) <= 0.5:
            raise ValueError("bandit_exploration must be 0 to 0.5")
        return float(v)

    @field_validator("cost_weight", "latency_weight", "window_days", "min_samples", "bandit_min_samples")
    @classmethod
    def _non_negative(cls, v):
        if v < 0:
            raise ValueError("must not be negative")
        return v


class PlannerTopSettings(Layered):
    dir: str = "config/planners"           # planner files, read through the storage backend
    default: str = "react"                 # an LLM tool's planner when it names none
    reload_interval_s: float = 2.0         # how often a lookup checks the files for changes
    python_builtins: bool = False          # true: react, plan_execute, recipes, router run the Python classes
    resume_ttl_s: int = 900                # how long a run paused at ask_user (MRTR) can be resumed
    dry_run_model: str = "mock/mock-planner"
    max_input_chars: int = 20000
    menu_min_pass_rate: float = 0.5        # a menu candidate whose latest eval run passed less is dropped
    numbers_check: str = "off"             # the reserved setting's default: off | warn | enforce

    @field_validator("numbers_check", mode="before")
    @classmethod
    def _numbers_check(cls, v):
        v = "off" if v is False else v              # YAML reads a bare ``off`` as false
        if v not in ("off", "warn", "enforce"):
            raise ValueError(f"numbers_check {v!r} is not one of off, warn, enforce")
        return v


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
    numbers_check: str = "off"             # the reserved setting's default: off | warn | enforce
    limits: PlannerLimitSettings = field(default_factory=PlannerLimitSettings)
    learning: PlannerLearningSettings = field(default_factory=PlannerLearningSettings)

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
                           limits=_resolve(PlannerLimitSettings, "planners_limits", raw.get("limits") or {}, environ),
                           learning=_resolve(PlannerLearningSettings, "planners_learning", raw.get("learning") or {},
                                             environ))


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
