"""
SAJHA MCP Server — the quantitative workspace (docs/architecture/Quantitative Planners.md §2).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Values that carry a unit, an as-of date and a source; a tested library of operations with a unit
check before each; and the run's workspace that holds them. This package has no model code and
calls no tools: planners (and later report narration) read tool results into quantities, name
operations, and SAJHA does the arithmetic.

Public API
----------

Quantities and units::

    from sajha.ai.quant import Quantity, Unit, parse_unit, Workspace, QuantError, UnitError

    q = Quantity.of(45, "bp")                                     # a constant
    cpi = Quantity.from_tool(310.3, "index", call_id="c1", tool="fred_cpi",
                             path="$.data.observations[0].value", as_of="2026-09")
    q.to("percent").value                                         # 0.45
    parse_unit("USD mn"), parse_unit("%"), parse_unit("USD/EUR")  # Unit(kind, code, scale)

- :class:`Quantity` ``(value, unit, as_of, source, lineage, name)``: ``value`` is a float, a column
  (list) or a grid (list of equal-length lists, at most ``ai.quant.max_table_cells`` cells);
  ``source`` is ``{"kind": "tool"|"constant"|"operation", ...}``; ``lineage`` (computed only) is
  ``{"op", "inputs", "args"}``. ``to(unit)`` converts; ``to_dict``/``from_dict`` serialise.
- :class:`Unit` and :func:`parse_unit`: kinds ``currency`` (ISO code, scale ``k|mn|bn|tn``),
  ``count`` (scale), ``percent``, ``pp``, ``bp``, ``ratio``, ``index``, ``days``, ``years``,
  ``unitless`` and ``per`` (``USD/EUR``, an FX rate quoting USD per EUR). :func:`convert_value`,
  :func:`conversion_factor`, :func:`equivalents` apply the rules of §2.2: percent ↔ pp ↔ bp ↔ ratio,
  scales of one currency or of count, days ↔ years by ``ai.quant.day_count``; never between
  currencies, never between a level and a rate.

Operations (§2.3), each a pure function that refuses with :class:`QuantError` / :class:`UnitError`
(``str(e)`` is written for the model)::

    from sajha.ai.quant import ops
    ops.bp_spread(Quantity.of(4.10, "percent"), Quantity.of(2.65, "percent"))   # 145 bp
    ops.operation("pct_change")                 # look up by name; ops.operations() lists signatures

``diff``, ``pp``, ``pct_change``, ``ratio``, ``bp_spread``, ``cagr``, ``annualise``, ``npv``,
``irr``, ``weighted_avg``, ``sum``, ``mean``, ``median``, ``stdev``, ``min``, ``max``,
``regression`` (a dict: ``slope``/``slope_<i>``, ``intercept``, ``r2``), ``correlation``,
``convert``, ``fx_convert``, ``round``.

The workspace::

    ws = workspace_of(plan_state, create=True)   # PlanState.data["workspace"], one per run
    ws.put("cpi_now", cpi); ws.put("cpi_then", Quantity.of(298.1, "index"))
    ws.run("pct_change", "cpi_then", "cpi_now", name="inflation")   # strings naming quantities resolve
    ws.lineage("inflation")                      # the tree back to the tool calls
    ws.to_json(); Workspace.from_json(data)      # for the run record
    ws.figures()                                 # (value, unit, name) in every convertible unit

Units a tool declares (``x-sajha-unit`` on an ``outputSchema`` property, §2.2)::

    schema_unit(tool.output_schema, "$.data.observations[0].value")   # "percent", or None

A read whose path the schema declares a unit for is recorded with that unit and
``unit_from: "schema"``; otherwise the planner's unit, ``unit_from: "declared"``.

The verify check ``numbers_in_workspace`` (sajha/ai/planners_engine/checks.py) matches an answer's
figures against the run's tool results and this workspace; the reserved planner setting
``numbers_check`` runs it after any planner's answer. Settings: :func:`quant_settings`
(``ai.quant.*``).
"""

from sajha.ai.quant.errors import QuantError, UnitError
from sajha.ai.quant.quantity import WORKSPACE_KEY, Quantity, Workspace, workspace_of
from sajha.ai.quant.schema_units import KEYWORD as UNIT_KEYWORD, schema_unit
from sajha.ai.quant.settings import QuantSettings, quant_settings, set_quant_settings
from sajha.ai.quant.units import (DAY_COUNTS, Unit, conversion_factor, convert_value, convertible, days_per_year,
                                  equivalents, parse_unit)
from sajha.ai.quant import ops  # noqa: E402  (registers the operations)
from sajha.ai.quant.ops import operation, operations

__all__ = ["QuantError", "UnitError", "Quantity", "Workspace", "workspace_of", "WORKSPACE_KEY", "Unit",
           "parse_unit", "conversion_factor", "convert_value", "convertible", "equivalents", "days_per_year",
           "DAY_COUNTS", "UNIT_KEYWORD", "schema_unit", "ops", "operation", "operations", "QuantSettings", "quant_settings", "set_quant_settings"]
