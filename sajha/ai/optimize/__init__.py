"""
SAJHA MCP Server — optimisation for the ``optimize`` planner (Quantitative Planners §3.6).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

    formulation.py  the restricted JSON form, parse_formulation() and its errors (no SciPy needed)
    solver.py       available(), solve() with SciPy (imported lazily), check_solution()
    stage.py        the ``optimize`` stage type (registered with the planner engine on first use)

SciPy is optional: without it ``solver.available()`` is false, the planner file
``config/planners/optimize.yaml`` is not loaded and an info notice says why.
"""

from sajha.ai.optimize.formulation import FormulationError, Problem, parse_formulation
from sajha.ai.optimize.solver import available, check_solution, solve

__all__ = ["FormulationError", "Problem", "available", "check_solution", "parse_formulation", "solve"]
