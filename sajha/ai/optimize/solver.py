"""
SAJHA MCP Server — solving a validated :class:`Problem` with SciPy, and the feasibility check.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Quantitative Planners.md §3.6.

- Linear, continuous: ``scipy.optimize.linprog`` (HiGHS).
- Linear with integer variables: ``scipy.optimize.milp`` (HiGHS).
- Convex quadratic (concave for ``max``), continuous: ``scipy.optimize.minimize`` (SLSQP), started
  from a feasible point found by ``linprog``. Unboundedness is decided exactly first (a recession
  direction that lowers the objective, found by ``linprog``). A non-convex quadratic objective, or a
  quadratic objective with integer variables, is refused: a local optimum would be reported as the
  answer, and that would be an invented solution.

Every solution then passes the **feasibility check**: each bound, each constraint and each
integrality requirement is evaluated at the solution within a tolerance; a solution that fails is
reported as ``check_failed``, never as a solution. Infeasible and unbounded problems are reported as
such. SciPy (and NumPy) are imported only when a problem is solved; :func:`available` says whether
they can be.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from sajha.ai.optimize.formulation import Problem

STATUSES = ("optimal", "infeasible", "unbounded", "check_failed", "unsupported", "error")
ABS_TOL = 1e-6
REL_TOL = 1e-7
INT_TOL = 1e-6

_AVAILABLE: Optional[Tuple[bool, str]] = None


def available(refresh: bool = False) -> Tuple[bool, str]:
    """(True, version) when SciPy's optimisers import, else (False, why). Cached."""
    global _AVAILABLE
    if _AVAILABLE is None or refresh:
        try:
            import scipy
            from scipy.optimize import linprog, milp, minimize  # noqa: F401
            _AVAILABLE = (True, f"SciPy {scipy.__version__}")
        except Exception as e:
            _AVAILABLE = (False, f"SciPy is not installed or does not import ({e.__class__.__name__}: "
                                 f"{str(e)[:160]}); install scipy to enable the optimize planner")
    return _AVAILABLE


class SolverUnavailable(RuntimeError):
    pass


def _tol(scale: float) -> float:
    return max(ABS_TOL, REL_TOL * scale)


def _arrays(p: Problem):
    import numpy as np
    idx = {n: i for i, n in enumerate(p.names)}
    n = len(idx)
    sign = 1.0 if p.sense == "min" else -1.0
    c = np.zeros(n)
    for k, v in p.linear.items():
        c[idx[k]] += v
    H = np.zeros((n, n))                  # objective = 0.5 x'Hx + c'x + constant
    for a, b, coef in p.quadratic:
        i, j = idx[a], idx[b]
        if i == j:
            H[i, i] += 2 * coef
        else:
            H[i, j] += coef
            H[j, i] += coef
    ub_rows, ub_rhs, eq_rows, eq_rhs = [], [], [], []
    for con in p.constraints:
        row = np.zeros(n)
        for k, v in con.terms.items():
            row[idx[k]] += v
        if con.op == "<=":
            ub_rows.append(row)
            ub_rhs.append(con.rhs)
        elif con.op == ">=":
            ub_rows.append(-row)
            ub_rhs.append(-con.rhs)
        else:
            eq_rows.append(row)
            eq_rhs.append(con.rhs)
    A_ub = np.array(ub_rows) if ub_rows else None
    b_ub = np.array(ub_rhs) if ub_rows else None
    A_eq = np.array(eq_rows) if eq_rows else None
    b_eq = np.array(eq_rhs) if eq_rows else None
    bounds = [(v.lower, v.upper) for v in p.variables]
    integrality = np.array([1 if v.integer else 0 for v in p.variables])
    return sign, c, H, A_ub, b_ub, A_eq, b_eq, bounds, integrality


def check_solution(p: Problem, x: Dict[str, float]) -> Dict[str, Any]:
    """Evaluate every bound, constraint and integrality requirement at ``x``."""
    rows: List[Dict[str, Any]] = []
    violations: List[str] = []
    for v in p.variables:
        val = x.get(v.name)
        if val is None or not math.isfinite(val):
            violations.append(f'{v.name} has no finite value')
            continue
        t = _tol(abs(val))
        if v.lower is not None and val < v.lower - t:
            violations.append(f"{v.name} = {val:.6g} is below its lower bound {v.lower:g}")
        if v.upper is not None and val > v.upper + t:
            violations.append(f"{v.name} = {val:.6g} is above its upper bound {v.upper:g}")
        if v.integer and abs(val - round(val)) > INT_TOL:
            violations.append(f"{v.name} = {val:.6g} is not an integer")
    for con in p.constraints:
        lhs = sum(coef * x.get(k, float("nan")) for k, coef in con.terms.items())
        scale = max(1.0, abs(con.rhs), sum(abs(coef * x.get(k, 0.0)) for k, coef in con.terms.items()))
        t = _tol(scale)
        if con.op == "<=":
            ok, slack = lhs <= con.rhs + t, con.rhs - lhs
        elif con.op == ">=":
            ok, slack = lhs >= con.rhs - t, lhs - con.rhs
        else:
            ok, slack = abs(lhs - con.rhs) <= t, -abs(lhs - con.rhs)
        ok = bool(ok) and math.isfinite(lhs)
        rows.append({"name": con.name, "lhs": lhs, "op": con.op, "rhs": con.rhs, "slack": slack, "ok": ok,
                     "binding": ok and abs(lhs - con.rhs) <= t, "tolerance": t})
        if not ok:
            violations.append(f'constraint "{con.name}": {lhs:.6g} {con.op} {con.rhs:g} does not hold')
    return {"ok": not violations, "violations": violations[:20], "constraints": rows}


def _feasible_point(p: Problem, arrays, time_limit: float):
    """A feasible point of the constraints (any objective), or None when there is none."""
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, linprog, milp
    _sign, _c, _H, A_ub, b_ub, A_eq, b_eq, bounds, integrality = arrays
    n = len(bounds)
    if integrality.any():
        cons = []
        if A_ub is not None:
            cons.append(LinearConstraint(A_ub, -np.inf, b_ub))
        if A_eq is not None:
            cons.append(LinearConstraint(A_eq, b_eq, b_eq))
        lo = np.array([-np.inf if b[0] is None else b[0] for b in bounds])
        hi = np.array([np.inf if b[1] is None else b[1] for b in bounds])
        r = milp(np.zeros(n), integrality=integrality, bounds=Bounds(lo, hi), constraints=cons or None,
                 options={"time_limit": time_limit})
    else:
        r = linprog(np.zeros(n), A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs",
                    options={"time_limit": time_limit})
    return r.x if r.status == 0 and r.x is not None else None


def _qp_unbounded(arrays, time_limit: float) -> bool:
    """A convex QP is unbounded below iff some recession direction d (A_ub d <= 0, A_eq d = 0, the
    bounds' recession cone, H d = 0) has c'd < 0. Found with one LP over the box -1 <= d <= 1."""
    import numpy as np
    from scipy.optimize import linprog
    sign, c, H, A_ub, b_ub, A_eq, b_eq, bounds, _int = arrays
    n = len(bounds)
    rbounds = []
    for lo, hi in bounds:
        rbounds.append((0.0 if lo is not None else -1.0, 0.0 if hi is not None else 1.0))
    eq = [H * sign] + ([A_eq] if A_eq is not None else [])
    A_e = np.vstack(eq)
    r = linprog(sign * c, A_ub=A_ub, b_ub=np.zeros(A_ub.shape[0]) if A_ub is not None else None,
                A_eq=A_e, b_eq=np.zeros(A_e.shape[0]), bounds=rbounds, method="highs",
                options={"time_limit": time_limit})
    return r.status == 0 and r.fun is not None and r.fun < -1e-9


def _ambiguous(p: Problem, arrays, time_limit: float) -> str:
    """HiGHS's "infeasible or unbounded": decide with a feasibility problem."""
    return "unbounded" if _feasible_point(p, arrays, time_limit) is not None else "infeasible"


def solve(p: Problem, time_limit: float = 10.0) -> Dict[str, Any]:
    """Solve ``p``. Returns ``{status, message, method, objective, values, check, seconds}``;
    ``values`` and ``objective`` only when ``status`` is ``optimal``."""
    ok, why = available()
    if not ok:
        raise SolverUnavailable(why)
    import numpy as np
    t0 = time.time()
    arrays = _arrays(p)
    sign, c, H, A_ub, b_ub, A_eq, b_eq, bounds, integrality = arrays
    names = p.names
    out: Dict[str, Any] = {"status": "error", "message": "", "method": "", "objective": None, "values": None,
                           "check": None}

    def finish(status: str, message: str, x=None) -> Dict[str, Any]:
        out.update(status=status, message=message, seconds=round(time.time() - t0, 4))
        if x is not None and status == "optimal":
            values = {n: float(v) for n, v in zip(names, x)}
            for var in p.variables:              # report integers as integers once they check out
                if var.integer and abs(values[var.name] - round(values[var.name])) <= INT_TOL:
                    values[var.name] = float(round(values[var.name]))
            chk = check_solution(p, values)
            out["check"] = chk
            if not chk["ok"]:
                out.update(status="check_failed", message="the solver returned a point that fails the "
                                                          "feasibility check: " + "; ".join(chk["violations"][:5]))
                return out
            out["values"] = values
            out["objective"] = p.objective_value(values)
        return out

    try:
        if p.is_quadratic:
            out["method"] = "minimize"
            if p.is_integer:
                return finish("unsupported", "a quadratic objective with integer variables is not supported")
            Hs = sign * H
            scale = max(1.0, float(np.abs(Hs).max()))
            if float(np.linalg.eigvalsh((Hs + Hs.T) / 2).min()) < -1e-9 * scale:
                return finish("unsupported", "the quadratic objective is not convex for minimisation (not concave "
                                             "for maximisation); only convex problems are solved, because a local "
                                             "optimum could be reported as the answer")
            x0 = _feasible_point(p, arrays, time_limit)
            if x0 is None:
                return finish("infeasible", "no point satisfies every constraint and bound")
            if _qp_unbounded(arrays, time_limit):
                return finish("unbounded", "the objective can improve without limit within the constraints")
            from scipy.optimize import minimize
            cons = []
            if A_ub is not None:
                cons.append({"type": "ineq", "fun": lambda x, A=A_ub, b=b_ub: b - A @ x,
                             "jac": lambda x, A=A_ub: -A})
            if A_eq is not None:
                cons.append({"type": "eq", "fun": lambda x, A=A_eq, b=b_eq: A @ x - b, "jac": lambda x, A=A_eq: A})
            fun = lambda x: sign * (0.5 * x @ H @ x + c @ x)          # noqa: E731
            jac = lambda x: sign * (H @ x + c)                          # noqa: E731
            r = minimize(fun, x0, jac=jac, bounds=bounds, constraints=cons, method="SLSQP",
                         options={"maxiter": 1000, "ftol": 1e-12})
            if not r.success:
                return finish("error", f"the solver did not converge: {r.message}")
            return finish("optimal", str(r.message), r.x)
        if p.is_integer:
            from scipy.optimize import Bounds, LinearConstraint, milp
            out["method"] = "milp"
            cons = []
            if A_ub is not None:
                cons.append(LinearConstraint(A_ub, -np.inf, b_ub))
            if A_eq is not None:
                cons.append(LinearConstraint(A_eq, b_eq, b_eq))
            lo = np.array([-np.inf if b[0] is None else b[0] for b in bounds])
            hi = np.array([np.inf if b[1] is None else b[1] for b in bounds])
            r = milp(sign * c, integrality=integrality, bounds=Bounds(lo, hi), constraints=cons or None,
                     options={"time_limit": time_limit})
        else:
            from scipy.optimize import linprog
            out["method"] = "linprog"
            r = linprog(sign * c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs",
                        options={"time_limit": time_limit})
        msg = str(r.message)
        if r.status == 0:
            return finish("optimal", msg, r.x)
        if r.status == 2:
            return finish("infeasible", "no point satisfies every constraint and bound")
        if r.status == 3:
            return finish("unbounded", "the objective can improve without limit within the constraints")
        if "infeasible or unbounded" in msg.lower() or "unbounded or infeasible" in msg.lower():
            st = _ambiguous(p, arrays, time_limit)
            return finish(st, "no point satisfies every constraint and bound" if st == "infeasible"
                          else "the objective can improve without limit within the constraints")
        if r.status == 1:
            return finish("error", f"the solver stopped at its iteration or time limit ({time_limit:g} s): {msg}")
        return finish("error", f"the solver failed: {msg}")
    except Exception as e:                      # a numerical failure is reported, never a solution
        return finish("error", f"the solver failed: {e.__class__.__name__}: {str(e)[:200]}")
