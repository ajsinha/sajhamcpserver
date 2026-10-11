"""
SAJHA MCP Server — the restricted JSON form of an optimisation problem, and its validation.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Reference: docs/architecture/Quantitative Planners.md §3.6. A model writes the formulation; this
module turns it into a :class:`Problem` or a list of plain-language errors (returned to the model).
It needs no SciPy and no NumPy.

The form::

    {"sense": "min" | "max",
     "variables":   [{"name": "x", "lower": 0, "upper": null, "integer": false}, ...],
     "objective":   {"linear": {"x": 3, "y": 2},
                     "quadratic": [{"a": "x", "b": "y", "coef": 1.5}, ...],     # optional: coef * x * y
                     "constant": 0},                                            # optional
     "constraints": [{"name": "budget", "terms": {"x": 1, "y": 1}, "op": "<=", "rhs": 10}, ...]}

Coefficients, bounds and right-hand sides are plain numbers by default. ``resolve`` is a callable
``(value, where) -> float`` that :func:`parse_formulation` applies to every number; the ``optimize``
stage passes one that also accepts the name of a workspace quantity (sajha/ai/optimize/stage.py).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

#: The hard ceiling on ``max_variables`` whatever a planner file's settings say.
MAX_VARIABLES_CEILING = 500
MAX_CONSTRAINTS = 1000
MAX_ERRORS = 20
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
OPS = ("<=", ">=", "==")

Resolver = Callable[[Any, str], float]


@dataclass
class Variable:
    name: str
    lower: Optional[float] = 0.0
    upper: Optional[float] = None
    integer: bool = False


@dataclass
class Constraint:
    name: str
    terms: Dict[str, float]
    op: str
    rhs: float


@dataclass
class Problem:
    sense: str
    variables: List[Variable]
    linear: Dict[str, float] = field(default_factory=dict)
    quadratic: List[Tuple[str, str, float]] = field(default_factory=list)
    constant: float = 0.0
    constraints: List[Constraint] = field(default_factory=list)

    @property
    def names(self) -> List[str]:
        return [v.name for v in self.variables]

    @property
    def is_quadratic(self) -> bool:
        return any(c != 0 for _a, _b, c in self.quadratic)

    @property
    def is_integer(self) -> bool:
        return any(v.integer for v in self.variables)

    def objective_value(self, x: Dict[str, float]) -> float:
        val = self.constant + sum(c * x[n] for n, c in self.linear.items())
        return val + sum(c * x[a] * x[b] for a, b, c in self.quadratic)

    def to_dict(self) -> Dict[str, Any]:
        return {"sense": self.sense,
                "variables": [{"name": v.name, "lower": v.lower, "upper": v.upper, "integer": v.integer}
                              for v in self.variables],
                "objective": {"linear": dict(self.linear),
                              "quadratic": [{"a": a, "b": b, "coef": c} for a, b, c in self.quadratic],
                              "constant": self.constant},
                "constraints": [{"name": c.name, "terms": dict(c.terms), "op": c.op, "rhs": c.rhs}
                                for c in self.constraints]}


class FormulationError(ValueError):
    """The formulation does not validate; ``errors`` are the messages for the model."""

    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def plain_number(value: Any, where: str) -> float:
    """The default resolver: a finite int or float (not a bool, not a string)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number, not {type(value).__name__} {str(value)[:40]!r}")
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{where} must be a finite number")
    return v


#: The JSON Schema a model's structured reply is checked against before validation.
FORMULATION_SCHEMA: Dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["sense", "variables", "objective", "constraints"],
    "properties": {
        "sense": {"type": "string", "enum": ["min", "max"]},
        "variables": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False, "required": ["name"],
            "properties": {"name": {"type": "string"}, "lower": {"type": ["number", "null"]},
                           "upper": {"type": ["number", "null"]}, "integer": {"type": "boolean"},
                           "description": {"type": "string"}}}},
        "objective": {"type": "object", "additionalProperties": False, "properties": {
            "linear": {"type": "object", "additionalProperties": {"type": "number"}},
            "quadratic": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["a", "b", "coef"],
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "coef": {"type": "number"}}}},
            "constant": {"type": "number"}}},
        "constraints": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["terms", "op", "rhs"],
            "properties": {"name": {"type": "string"},
                           "terms": {"type": "object", "additionalProperties": {"type": "number"}},
                           "op": {"type": "string", "enum": list(OPS)}, "rhs": {"type": "number"}}}},
    },
}


def parse_formulation(data: Any, max_variables: int = 50, resolve: Optional[Resolver] = None) -> Problem:
    """Validate ``data`` and build a :class:`Problem`; raises :class:`FormulationError` with every
    error found (at most 20), each naming where it is."""
    resolve = resolve or plain_number
    limit = max(1, min(int(max_variables or 1), MAX_VARIABLES_CEILING))
    errors: List[str] = []

    def num(value: Any, where: str, optional: bool = False) -> Optional[float]:
        if value is None and optional:
            return None
        try:
            return resolve(value, where)
        except (TypeError, ValueError) as e:
            errors.append(str(e))
            return None

    if not isinstance(data, dict):
        raise FormulationError(["the formulation must be a JSON object"])
    unknown = set(data) - {"sense", "variables", "objective", "constraints"}
    if unknown:
        errors.append(f"unknown keys: {', '.join(sorted(unknown))}")
    sense = data.get("sense", "min")
    if sense not in ("min", "max"):
        errors.append('sense must be "min" or "max"')

    variables: List[Variable] = []
    raw_vars = data.get("variables")
    if not isinstance(raw_vars, list) or not raw_vars:
        errors.append("variables must be a non-empty list")
        raw_vars = []
    elif len(raw_vars) > limit:
        errors.append(f"{len(raw_vars)} variables; at most {limit} (settings.max_variables)")
        raw_vars = raw_vars[:limit]
    seen = set()
    for i, rv in enumerate(raw_vars):
        where = f"variables[{i}]"
        if not isinstance(rv, dict):
            errors.append(f"{where} must be an object")
            continue
        name = rv.get("name")
        if not isinstance(name, str) or not NAME.match(name):
            errors.append(f"{where}.name must be an identifier (letters, digits, underscore)")
            continue
        if name in seen:
            errors.append(f'variable "{name}" is declared twice')
            continue
        seen.add(name)
        lower = num(rv.get("lower", 0), f'the lower bound of "{name}"', optional=True)
        upper = num(rv.get("upper"), f'the upper bound of "{name}"', optional=True)
        integer = rv.get("integer", False)
        if not isinstance(integer, bool):
            errors.append(f'"integer" of "{name}" must be true or false')
            integer = False
        if lower is not None and upper is not None and lower > upper:
            errors.append(f'variable "{name}": the lower bound {lower:g} is above the upper bound {upper:g}')
        variables.append(Variable(name, lower, upper, integer))
    names = {v.name for v in variables}

    def terms_of(raw: Any, where: str) -> Dict[str, float]:
        out: Dict[str, float] = {}
        if not isinstance(raw, dict):
            errors.append(f"{where} must be an object of variable: coefficient")
            return out
        for k, v in raw.items():
            if k not in names:
                errors.append(f'{where} names "{k}", which is not a variable')
                continue
            c = num(v, f'{where}["{k}"]')
            if c is not None:
                out[k] = c
        return out

    obj = data.get("objective")
    linear: Dict[str, float] = {}
    quadratic: List[Tuple[str, str, float]] = []
    constant = 0.0
    if not isinstance(obj, dict):
        errors.append("objective must be an object with linear (and optionally quadratic) terms")
    else:
        bad = set(obj) - {"linear", "quadratic", "constant"}
        if bad:
            errors.append(f"objective: unknown keys {', '.join(sorted(bad))}")
        linear = terms_of(obj.get("linear") or {}, "objective.linear")
        rq = obj.get("quadratic") or []
        if not isinstance(rq, list):
            errors.append("objective.quadratic must be a list of {a, b, coef}")
            rq = []
        for i, t in enumerate(rq):
            where = f"objective.quadratic[{i}]"
            if not isinstance(t, dict) or not {"a", "b", "coef"} <= set(t):
                errors.append(f"{where} must be {{a, b, coef}}")
                continue
            if t["a"] not in names or t["b"] not in names:
                errors.append(f"{where} names a variable that is not declared")
                continue
            c = num(t["coef"], f"{where}.coef")
            if c is not None:
                quadratic.append((t["a"], t["b"], c))
        c0 = num(obj.get("constant", 0), "objective.constant")
        constant = c0 if c0 is not None else 0.0
        if not linear and not quadratic:
            errors.append("the objective has no terms")

    constraints: List[Constraint] = []
    raw_cons = data.get("constraints", [])
    if not isinstance(raw_cons, list):
        errors.append("constraints must be a list")
        raw_cons = []
    if len(raw_cons) > MAX_CONSTRAINTS:
        errors.append(f"{len(raw_cons)} constraints; at most {MAX_CONSTRAINTS}")
        raw_cons = raw_cons[:MAX_CONSTRAINTS]
    for i, rc in enumerate(raw_cons):
        where = f"constraints[{i}]"
        if not isinstance(rc, dict):
            errors.append(f"{where} must be an object")
            continue
        cname = rc.get("name") or f"c{i + 1}"
        if not isinstance(cname, str):
            cname = f"c{i + 1}"
        cname = cname[:64]
        op = rc.get("op")
        if op not in OPS:
            errors.append(f'{where} ("{cname}"): op must be one of {", ".join(OPS)}')
            continue
        terms = terms_of(rc.get("terms"), f'{where} ("{cname}").terms')
        if not terms and isinstance(rc.get("terms"), dict) and not rc["terms"]:
            errors.append(f'{where} ("{cname}") has no terms')
        rhs = num(rc.get("rhs"), f'{where} ("{cname}").rhs')
        if terms and rhs is not None:
            constraints.append(Constraint(cname, terms, op, rhs))
    if errors:
        raise FormulationError(errors[:MAX_ERRORS])
    return Problem(sense=sense, variables=variables, linear=linear, quadratic=quadratic, constant=constant,
                   constraints=constraints)
