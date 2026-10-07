"""
SAJHA MCP Server — planner metrics (Planner Reference §10.4; Observability owns the list).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from sajha.observability.metrics import REGISTRY, Counter, Histogram

    STAGES = Counter(REGISTRY, "sajha_planner_stages_total", "Planner stages run, by planner, stage and outcome.",
                     ("planner", "stage", "outcome"))
    LOOPS = Counter(REGISTRY, "sajha_planner_loops_exhausted_total",
                    "Bounded planner edges taken to their on_exhausted target.", ("planner", "edge"))
    RUN_SECONDS = Histogram(REGISTRY, "sajha_planner_run_seconds", "Planner run duration in seconds.", ("planner",))
    EXPR_ERRORS = Counter(REGISTRY, "sajha_planner_expression_errors_total",
                          "Planner expressions that failed at run time (the condition counted as false).",
                          ("planner",))
    LOAD_ERRORS = Counter(REGISTRY, "sajha_planner_load_errors_total",
                          "Planner files refused at load (the last good version stays in use).", ("planner",))
    CHOSEN = Counter(REGISTRY, "sajha_planner_chosen_total", "Planners chosen, by tool, planner and why.",
                     ("tool", "planner", "by"))
except Exception as _e:          # metrics must never break a run
    logger.debug(f"planner metrics unavailable: {_e}")
    STAGES = LOOPS = RUN_SECONDS = EXPR_ERRORS = LOAD_ERRORS = CHOSEN = None


def _enabled() -> bool:
    try:
        from sajha.observability import settings as S
        return S.metrics_enabled()
    except Exception:
        return True


def stage(planner: str, stage_id: str, outcome: str) -> None:
    if STAGES is not None and _enabled():
        STAGES.inc((planner, stage_id, outcome))


def loop_exhausted(planner: str, edge: str) -> None:
    if LOOPS is not None and _enabled():
        LOOPS.inc((planner, edge))


def run_seconds(planner: str, seconds: float) -> None:
    if RUN_SECONDS is not None and _enabled():
        RUN_SECONDS.observe((planner,), seconds)


def expression_error(planner: str) -> None:
    if EXPR_ERRORS is not None and _enabled():
        EXPR_ERRORS.inc((planner,))


def load_error(planner: str) -> None:
    if LOAD_ERRORS is not None:
        LOAD_ERRORS.inc((planner,))


def chosen(tool: str, planner: str, by: str) -> None:
    if CHOSEN is not None and _enabled():
        CHOSEN.inc((tool, planner, by))
