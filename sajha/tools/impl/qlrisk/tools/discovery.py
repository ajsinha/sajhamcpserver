# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""catalog: what qlrisk can price and compute, read from the installed qlrisk."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from .. import introspect as I
from ..inputs import InvalidInput, build_market_data
from ..jsonable import to_jsonable
from . import Ctx, ToolDef, obj
from .products import exposed_fields, tool_name, trade_item_schema

TOPICS = ["products", "calculators", "stress_scenarios", "report_measures", "processes", "market_data",
          "enumerations", "version"]


def _catalog(args: Dict[str, Any], ctx: Ctx):
    import qlrisk
    topic = args["topic"]
    name = args.get("name")
    if topic == "products":
        classes = I.product_classes()
        if name:
            if name not in classes:
                raise InvalidInput(f"name {name!r} is not a qlrisk product; omit name to list them")
            spec = I.product_spec(name)
            fields = exposed_fields(name)
            return {"product": {k: spec[k] for k in ("name", "category", "product_type", "asset_class", "description")},
                    "pricing_tool": tool_name(name), "trade_schema": trade_item_schema(name)}, \
                (f"{name}: {spec['category']} product; inputs {[e.name for e in fields if not e.advanced]}, "
                 f"required {[e.name for e in fields if e.required]} (rates in percent, spreads in bp)")
        rows = []
        for n in classes:
            s = I.product_spec(n)
            if args.get("category") and s["category"] != args["category"]:
                continue
            fields = exposed_fields(n)
            rows.append({"name": n, "pricing_tool": tool_name(n), "category": s["category"], "asset_class": s["asset_class"],
                         "product_type": s["product_type"], "description": s["description"],
                         "required": [e.name for e in fields if e.required],
                         "inputs": [e.name for e in fields if not e.advanced],
                         "trade_fields": [e.name for e in fields if e.advanced]})
        cats = sorted({r["category"] for r in rows})
        return {"count": len(rows), "categories": cats, "products": rows}, \
            f"{len(rows)} qlrisk products in {len(cats)} categories"
    if topic == "calculators":
        from ..generate import CALC_INPUTS
        from ..units import calc_config_schema, calc_inputs_schema

        def summary(m):
            """qlrisk's calculator, with its inputs and config in the tools' names and units where they convert."""
            s = I.calculator_summary(m)
            if m in CALC_INPUTS:
                s["input_schema"] = calc_inputs_schema(m)
                s["config"] = calc_config_schema(m)["properties"]
            return s
        if name:
            if name not in I.CALCULATORS:
                raise InvalidInput(f"name {name!r} is not a calculator measure; choose from {sorted(I.CALCULATORS)}")
            s = summary(name)
            return s, f"{name}: {s['calculator']} ({s['calculator_type']})"
        rows = []
        for m in I.CALCULATORS:
            s = summary(m)
            rows.append({"measure": m, "calculator_type": s["calculator_type"], "calculator": s["calculator"],
                         "description": s["description"], "inputs": list(s["input_schema"]["properties"]),
                         "required": s["input_schema"].get("required", []), "config": s["config"]})
        tools = {"qlrisk_credit_risk": ["pd", "lgd", "ead", "el", "economic_capital", "raroc"],
                 "qlrisk_ccr_exposure": ["ce", "ee", "eee", "pfe", "peak", "stressed"],
                 "qlrisk_xva": ["cva", "dva", "fva", "kva", "mva"], "qlrisk_initial_margin": ["initial_margin"], "qlrisk_saccr": ["saccr"]}
        return {"count": len(rows), "calculators": rows, "tool_for_measure": tools}, f"{len(rows)} qlrisk calculators"
    if topic == "stress_scenarios":
        from ..generate import STRESS_DEFINITION
        from ..units import from_qlrisk, stress_definition_schema
        lib = {k: from_qlrisk(STRESS_DEFINITION, v) for k, v in I.stress_library().items()}
        return {"scenarios": lib, "definition_schema": stress_definition_schema(),
                "units": "equity_pct, vol_pct, credit_pct, commodity_pct, fx_usd_pct, fx_pct: relative moves in percent; "
                         "rates_bp: absolute, in basis points (two numbers: a 2y-10y twist)"}, \
            f"{len(lib)} historical stress scenarios: {', '.join(lib)}"
    if topic == "report_measures":
        m = I.report_measures()
        return m, f"qlrisk_risk_report measures: {', '.join(m['all'])} (default {', '.join(m['default'])})"
    if topic == "processes":
        return {"processes": I.supported_processes(), "parameters": I.path_params_schema(),
                "bounds": {"max_paths": ctx.limits.max_mc_paths, "max_time_steps": ctx.limits.max_time_steps}}, \
            f"{len(I.supported_processes())} stochastic processes: {', '.join(I.supported_processes())}"
    if topic == "market_data":
        from qlrisk.riskfactors import enumerate_risk_factors
        md = build_market_data(args.get("market_data"), None, ctx.warnings)
        factors = [str(f) for f in enumerate_risk_factors(md)]
        snapshot = {k: to_jsonable(getattr(md, k)) for k in I.market_data_fields() if k != "correlation_matrix"}
        return {"fields": I.market_data_fields(), "snapshot": snapshot, "risk_factors": factors}, \
            f"market data on {md.valuation_date}: {len(factors)} risk factors"
    if topic == "enumerations":
        e = I.enumerations()
        if name:
            if name not in e:
                raise InvalidInput(f"name {name!r} is not an enumeration; choose from {sorted(e)}")
            return {name: e[name]}, f"{name}: {len(e[name])} values"
        return e, f"{len(e)} qlrisk enumerations"
    if topic == "version":
        return {"qlrisk_version": qlrisk.__version__, "bounds": ctx.limits.as_dict(),
                "products": len(I.product_classes()), "calculators": len(I.CALCULATORS),
                "processes": I.supported_processes()}, f"qlrisk {qlrisk.__version__}"
    raise InvalidInput(f"topic must be one of {TOPICS}")


def tools(limits) -> List[ToolDef]:
    cats = sorted({I.product_spec(n)["category"] for n in I.product_classes()})
    return [ToolDef(
        name="catalog",
        title="qlrisk catalog",
        description=(
            "Discover what qlrisk can do before calling another tool. topic='products' lists every product "
            "(name, category, required fields, terms); add name='InterestRateSwap' for its full trade schema. "
            "topic='calculators' lists the credit, exposure, XVA, margin and SA-CCR calculators with their input fields "
            "and configuration (name='cva' for one). Other topics: 'stress_scenarios' (the historical crisis library), "
            "'report_measures' (qlrisk_risk_report measures), 'processes' (Monte Carlo processes and parameters), "
            "'market_data' (the sample snapshot and every risk-factor key, e.g. 'EQ.SPX', 'IR.FWD.SOFR.5Y'), "
            "'enumerations' (currencies, indices, frequencies, risk classes ...), 'version' (qlrisk version and work bounds). "
            "Example: {\"topic\": \"products\", \"category\": \"fx\"}."),
        input_schema=obj({
            "topic": {"type": "string", "enum": TOPICS},
            "name": {"type": "string", "description": "products: a product class; calculators: a measure; enumerations: an enum name."},
            "category": {"type": "string", "enum": cats, "description": "products: only this category."},
            "market_data": {"type": "object", "description": "market_data: overlay to inspect (same shape as other tools' market_data)."},
        }, ["topic"]),
        handler=_catalog,
    )]
