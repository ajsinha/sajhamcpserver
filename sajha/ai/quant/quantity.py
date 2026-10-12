"""
SAJHA MCP Server — quantities and the workspace that holds them (Quantitative Planners §2.1).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A :class:`Quantity` is a number (or a column or grid of numbers) with a unit, an as-of date, a
source and, when it was computed, its lineage. A :class:`Workspace` holds one run's named
quantities, runs operations on them by name (so each result records which quantities it came
from) and serialises to JSON for the run record.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Union

from sajha.ai.quant.errors import QuantError
from sajha.ai.quant.units import Unit, UnitLike, convert_value, parse_unit

Value = Union[float, List[float], List[List[float]]]
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,63}$")
WORKSPACE_KEY = "workspace"            # PlanState.data key the run's workspace lives under


def _max_cells() -> int:
    try:
        from sajha.ai.quant.settings import quant_settings
        return int(quant_settings().max_table_cells)
    except Exception:
        return 10000


def _num(v: Any, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        try:
            v = float(str(v).replace(",", "").strip())
        except (TypeError, ValueError):
            raise QuantError(f"{where}: {v!r} is not a number", "not_a_number")
    f = float(v)
    if math.isnan(f) or math.isinf(f):
        raise QuantError(f"{where}: {v!r} is not a finite number", "not_a_number")
    return f


def normalise_value(value: Any, max_cells: Optional[int] = None) -> Value:
    """A float, a list of floats (a column) or a list of equal-length lists (a grid), checked."""
    limit = _max_cells() if max_cells is None else max_cells
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(r, (list, tuple)) for r in value):
            width = len(value[0])
            if any(len(r) != width for r in value):
                raise QuantError("a table's rows must all have the same length", "bad_table")
            if len(value) * width > limit:
                raise QuantError(f"a table quantity has at most {limit} cells (ai.quant.max_table_cells); "
                                 f"this one has {len(value) * width}", "too_large")
            return [[_num(x, f"row {i}") for x in r] for i, r in enumerate(value)]
        if len(value) > limit:
            raise QuantError(f"a table quantity has at most {limit} cells (ai.quant.max_table_cells); "
                             f"this one has {len(value)}", "too_large")
        return [_num(x, f"item {i}") for i, x in enumerate(value)]
    return _num(value, "value")


@dataclass
class Quantity:
    """A number with what is needed to trust it.

    ``value``: a float, a column (list of floats) or a grid (list of equal-length lists).
    ``unit``: a :class:`Unit` (strings are parsed: ``"USD mn"``, ``"percent"``, ``"bp"``).
    ``as_of``: the date or period the value describes, when known.
    ``source``: where it came from: ``{"kind": "tool", "call_id", "tool", "version", "arguments",
    "path", "unit_from": "declared"|"schema"}``, ``{"kind": "constant", "text"}`` or
    ``{"kind": "operation", "op"}``.
    ``lineage``: for a computed quantity ``{"op", "inputs": [names], "args"}``; inputs are workspace
    names when the operation ran through a :class:`Workspace`.
    ``name``: its name in a workspace (set by :meth:`Workspace.put`).
    """
    value: Value
    unit: Unit = field(default_factory=lambda: Unit("unitless"))
    as_of: Optional[str] = None
    source: Dict[str, Any] = field(default_factory=lambda: {"kind": "constant"})
    lineage: Optional[Dict[str, Any]] = None
    name: Optional[str] = None

    def __post_init__(self):
        self.unit = parse_unit(self.unit)
        self.value = normalise_value(self.value)
        if self.as_of is not None:
            self.as_of = str(self.as_of)

    # constructors
    @classmethod
    def of(cls, value: Any, unit: UnitLike = None, as_of: Optional[str] = None, **source: Any) -> "Quantity":
        """A constant (from the question, or a test): ``Quantity.of(45, "bp")``."""
        return cls(value, parse_unit(unit), as_of, {"kind": "constant", **source})

    @classmethod
    def from_tool(cls, value: Any, unit: UnitLike, *, call_id: str, tool: str, path: str = "",
                  arguments: Optional[Dict[str, Any]] = None, version: str = "", as_of: Optional[str] = None,
                  unit_from: str = "declared") -> "Quantity":
        """A value read from a tool result. ``unit_from`` is ``schema`` when the tool's outputSchema
        declared the unit, else ``declared`` (the planner's, that is the model's, declaration)."""
        return cls(value, parse_unit(unit), as_of, {"kind": "tool", "call_id": call_id, "tool": tool,
                                                    "version": version, "arguments": dict(arguments or {}),
                                                    "path": path, "unit_from": unit_from})

    # shape
    @property
    def is_scalar(self) -> bool:
        return not isinstance(self.value, list)

    @property
    def is_column(self) -> bool:
        return isinstance(self.value, list) and not (self.value and isinstance(self.value[0], list))

    def cells(self) -> Iterator[float]:
        """Every number in the value (a scalar yields itself)."""
        if self.is_scalar:
            yield self.value          # type: ignore[misc]
        elif self.is_column:
            yield from self.value     # type: ignore[misc]
        else:
            for row in self.value:    # type: ignore[union-attr]
                yield from row

    def to(self, unit: UnitLike, day_count: Optional[str] = None) -> "Quantity":
        """This quantity in another unit (only conversions §2.2 allows; :class:`UnitError` otherwise)."""
        target = parse_unit(unit)
        if day_count is None and (self.unit.is_time or target.is_time):
            from sajha.ai.quant.settings import quant_settings
            day_count = quant_settings().day_count
        out = copy.deepcopy(self)
        out.value = convert_value(self.value, self.unit, target, day_count)
        out.unit = target
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": str(self.unit), "as_of": self.as_of,
                "source": self.source, "lineage": self.lineage}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Quantity":
        return cls(d["value"], parse_unit(d.get("unit")), d.get("as_of"), dict(d.get("source") or {}),
                   d.get("lineage"), d.get("name"))

    def __str__(self) -> str:
        v = self.value if not self.is_scalar else f"{self.value:g}"
        return f"{v} {self.unit}"


class Workspace:
    """One run's named quantities. ``put``/``get`` by name; ``run(op, ...)`` runs an operation of
    the library on named quantities (or Quantity objects) and stores the result with its lineage;
    ``lineage(name)`` is the tree back to the tool calls; ``to_json``/``from_json`` for the run record."""

    def __init__(self, quantities: Optional[Dict[str, Quantity]] = None):
        self._q: Dict[str, Quantity] = {}
        self._auto = 0
        for n, q in (quantities or {}).items():
            self.put(n, q)

    # access
    def put(self, name: str, q: Quantity, replace: bool = False) -> Quantity:
        if not isinstance(name, str) or not NAME.match(name):
            raise QuantError(f"quantity name {name!r} is not an identifier (letters, digits, '_' and '.', at most "
                             f"64 characters)", "bad_name")
        if name in self._q and not replace:
            raise QuantError(f"the workspace already has a quantity named {name}", "duplicate")
        if not isinstance(q, Quantity):
            raise QuantError(f"{name}: not a Quantity", "bad_quantity")
        q.name = name
        self._q[name] = q
        return q

    def get(self, name: str) -> Quantity:
        if name not in self._q:
            known = ", ".join(sorted(self._q)[:20]) or "none"
            raise QuantError(f"there is no quantity named {name} (known: {known})", "unknown_quantity")
        return self._q[name]

    def remove(self, name: str) -> None:
        """Drop a quantity (a computation graph replaced by its re-plan); no error when absent."""
        self._q.pop(name, None)

    def __contains__(self, name: str) -> bool:
        return name in self._q

    def __len__(self) -> int:
        return len(self._q)

    def __iter__(self) -> Iterator[Quantity]:
        return iter(list(self._q.values()))

    def names(self) -> List[str]:
        return list(self._q)

    # operations
    def run(self, op: str, *args: Any, name: Optional[str] = None, **kwargs: Any):
        """Run operation ``op`` of the library. Positional and keyword arguments that are strings
        naming a workspace quantity are replaced by that quantity. The result (a Quantity, or for
        ``regression`` a dict of them) is stored under ``name`` (``name.<part>`` for a dict) and
        returned. A refusal raises :class:`QuantError` and stores nothing."""
        from sajha.ai.quant.ops import operation
        fn = operation(op)

        def resolve(v: Any) -> Any:
            if isinstance(v, str) and v in self._q:
                return self._q[v]
            if isinstance(v, (list, tuple)) and v and all(isinstance(x, str) and x in self._q for x in v):
                return [self._q[x] for x in v]
            return v
        out = fn(*[resolve(a) for a in args], **{k: resolve(v) for k, v in kwargs.items()})
        if name is None:
            self._auto += 1
            name = f"{op}_{self._auto}"
        if isinstance(out, dict):
            for part, q in out.items():
                self.put(f"{name}.{part}", q)
        else:
            self.put(name, out)
        return out

    def lineage(self, name: str, _depth: int = 0) -> Dict[str, Any]:
        """``{name, value, unit, source, op?, args?, inputs: [lineage...]}`` back to the sources."""
        q = self.get(name)
        node: Dict[str, Any] = {"name": name, "value": q.value, "unit": str(q.unit), "as_of": q.as_of,
                                "source": q.source}
        if q.lineage and _depth < 50:
            node["op"] = q.lineage.get("op")
            node["args"] = q.lineage.get("args") or {}
            node["inputs"] = [self.lineage(i, _depth + 1) if isinstance(i, str) and i in self._q
                              else (i if isinstance(i, dict) else {"value": i})
                              for i in q.lineage.get("inputs") or []]
        return node

    def view(self, names: List[str], max_cells: int = 24, limit: int = 200) -> Dict[str, Dict[str, Any]]:
        """The quantities ``names`` and every quantity their lineage reaches, each compact for a page:
        ``{name: {value, cells, unit, as_of, source, op?, args?, inputs?}}``. A column or grid keeps its
        first ``max_cells`` numbers (``cells`` is the full count); inputs that are not workspace
        quantities stay inline (``{value, unit, source}``)."""
        def clip(v: Any) -> Any:
            if not isinstance(v, list):
                return v
            flat = [x for r in v for x in (r if isinstance(r, list) else [r])]
            return flat[:max_cells]
        out: Dict[str, Dict[str, Any]] = {}
        todo = [n for n in names if n in self._q]
        while todo and len(out) < limit:
            name = todo.pop(0)
            if name in out:
                continue
            q = self._q[name]
            cells = sum(1 for _ in q.cells())
            node: Dict[str, Any] = {"value": clip(q.value), "cells": cells, "unit": str(q.unit), "as_of": q.as_of,
                                    "source": q.source}
            if q.lineage:
                node["op"] = q.lineage.get("op")
                node["args"] = q.lineage.get("args") or {}
                ins = []
                for i in q.lineage.get("inputs") or []:
                    if isinstance(i, str) and i in self._q:
                        ins.append(i)
                        if i not in out:
                            todo.append(i)
                    elif isinstance(i, dict):
                        ins.append({"value": clip(i.get("value")), "unit": i.get("unit"), "source": i.get("source")})
                    else:
                        ins.append({"value": clip(i)})
                node["inputs"] = ins
            out[name] = node
        return out

    def figures(self, day_count: Optional[str] = None, limit: int = 100000) -> List[tuple]:
        """``(value, Unit, name)`` for every number of every quantity, in its own unit and in every
        unit it converts to (§2.2): what a figure in an answer may match (the numbers validator)."""
        from sajha.ai.quant.units import conversion_factor, equivalents
        if day_count is None:
            try:
                from sajha.ai.quant.settings import quant_settings
                day_count = quant_settings().day_count
            except Exception:
                day_count = "act/365"
        out: List[tuple] = []
        for q in self._q.values():
            for u in equivalents(q.unit):
                f = conversion_factor(q.unit, u, day_count)
                for v in q.cells():
                    out.append((v * f, u, q.name))
                    if len(out) >= limit:
                        return out
        return out

    # serialisation
    def to_json(self) -> Dict[str, Any]:
        return {"quantities": [q.to_dict() for q in self._q.values()]}

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "Workspace":
        ws = cls()
        for d in (data or {}).get("quantities") or []:
            ws.put(d["name"], Quantity.from_dict(d))
        return ws


def workspace_of(state: Any, create: bool = False) -> Optional[Workspace]:
    """The run's workspace: ``state.data["workspace"]`` of a PlanState (or a plain dict). With
    ``create`` a missing one is created; otherwise None when the run has none."""
    data = state if isinstance(state, dict) else getattr(state, "data", None)
    if not isinstance(data, dict):
        return None
    ws = data.get(WORKSPACE_KEY)
    if isinstance(ws, Workspace):
        return ws
    if create:
        ws = Workspace()
        data[WORKSPACE_KEY] = ws
        return ws
    return None
