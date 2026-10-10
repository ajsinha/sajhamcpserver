# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""price_trades and sensitivities: what a book is worth and what moves it."""

from __future__ import annotations

from typing import Any, Dict, List

from .. import introspect as I
from ..inputs import InvalidInput, build_market_data, build_trades, pv_in
from ..jsonable import key_str, rounded, to_jsonable
from . import Ctx, ToolDef, obj, portfolio_props

LADDER_VERTICES = ["native", "frtb_girr", "frtb_csr", "standard"]


def _price(args: Dict[str, Any], ctx: Ctx):
    md = build_market_data(args.get("market_data"))
    trades = build_trades(args["trades"], md, ctx.limits, ctx.warnings)
    ccy = args.get("reporting_currency", "USD")
    rows, total, errors = [], 0.0, []
    for t in trades:
        try:
            res = t.price(md)
            native, native_ccy, rep = pv_in(t, md, ccy)
        except Exception as exc:
            errors.append({"trade_id": t.trade_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        total += rep
        row = {"trade_id": t.trade_id, "product": type(t).__name__, "npv": native, "currency": native_ccy,
               "npv_reporting": rep, "components": to_jsonable(res.components), "greeks": to_jsonable(res.greeks),
               "risk_measures": to_jsonable(res.risk_measures)}
        if args.get("include_cash_flows"):
            row["cash_flows"] = to_jsonable(res.cash_flows)
        rows.append(row)
    out = {"valuation_date": md.valuation_date.isoformat(), "reporting_currency": ccy, "total_npv": total,
           "trades": rows, "errors": errors}
    return out, f"{len(rows)} trade(s) priced on {md.valuation_date}: total NPV {rounded(total)} {ccy}" + \
        (f"; {len(errors)} failed" if errors else "")


def _vertices(choice: str):
    from qlrisk.sensitivities import FRTB_CSR_VERTICES, FRTB_GIRR_VERTICES, STANDARD_TENORS
    return {"native": None, "frtb_girr": FRTB_GIRR_VERTICES, "frtb_csr": FRTB_CSR_VERTICES,
            "standard": STANDARD_TENORS}[choice]


def _sens(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.riskfactors import RiskClass, as_key
    from qlrisk.sensitivities import SensitivityEngine
    md = build_market_data(args.get("market_data"))
    trades = build_trades(args["trades"], md, ctx.limits, ctx.warnings)
    ccy = args.get("reporting_currency", "USD")
    eng = SensitivityEngine(method=args.get("bump_method", "central"))
    factors = None
    if args.get("factors"):
        try:
            factors = [as_key(f) for f in args["factors"]]
        except Exception as exc:
            raise InvalidInput(f"factors: {exc}") from None
    rcs = [RiskClass(r) for r in args["risk_classes"]] if args.get("risk_classes") else None
    res = eng.compute(trades, md, factors=factors, risk_classes=rcs, reporting_currency=ccy,
                      include_theta=args.get("include_theta", True))
    by_class = res.aggregate(("risk_class", "measure"))
    gamma = res.aggregate(("risk_class", "measure"), value="gamma")
    by_trade = res.aggregate(("trade_id", "measure"))
    out: Dict[str, Any] = {
        "valuation_date": md.valuation_date.isoformat(), "reporting_currency": ccy,
        "base_pv": to_jsonable(res.base_pv),
        "by_risk_class": [{"risk_class": rc.value, "measure": m.value, "value": v} for (rc, m), v in by_class.items()],
        "gamma_by_risk_class": [{"risk_class": rc.value, "measure": m.value, "gamma": v} for (rc, m), v in gamma.items()],
        "by_trade": [{"trade_id": t, "measure": m.value, "value": v} for (t, m), v in by_trade.items()],
        "theta": to_jsonable(res.theta()),
        "by_factor": {str(k): v for k, v in res.by_factor().items() if v},
        "errors": [{"trade_id": e.trade_id, "factor": str(e.factor) if e.factor else None, "message": e.message} for e in res.errors],
    }
    if args.get("include_ladders", True):
        ladders = []
        for (field, name, measure), lad in res.ladders(_vertices(args.get("ladder_vertices", "native"))).items():
            if any(lad.values.values()):
                ladders.append({"field": field, "name": name, "measure": measure.value,
                                "buckets": {key_str(k): v for k, v in sorted(lad.values.items())}})
        out["ladders"] = ladders
    cg = args.get("cross_gamma_factors")
    if cg:
        if len(cg) < 2:
            raise InvalidInput("cross_gamma_factors needs at least two factors")
        if len(cg) > ctx.limits.max_cross_gamma_factors:
            raise InvalidInput(f"cross_gamma_factors: {len(cg)} exceeds max_cross_gamma_factors={ctx.limits.max_cross_gamma_factors}")
        cross = eng.cross_gamma(trades, md, cg, reporting_currency=ccy)
        out["cross_gamma"] = [{"trade_id": r.trade_id, "factor": str(r.factor), "value": r.value,
                               "meta": to_jsonable(getattr(r, "meta", None) or {})} for r in cross.records]
    totals = {m: sum(v for (rc, mm), v in by_class.items() if mm.value == m) for m in {m.value for _, m in by_class}}
    summary = ", ".join(f"{m.upper()} {rounded(v)}" for m, v in sorted(totals.items()))
    return out, f"Sensitivities in {ccy} for {len(trades)} trade(s): {summary or 'none'}"


def tools(limits) -> List[ToolDef]:
    return [
        ToolDef(
            name="price_trades",
            title="Price trades",
            description=(
                "Price one or more trades with qlrisk: NPV in the trade currency and the reporting currency, pricing "
                "components (forward, vol, spread ...), analytic Greeks where the pricer gives them, and optional cash flows. "
                "Use this for 'what is it worth'; use qlrisk_sensitivities for DV01/CS01/delta/vega/theta. Market data defaults to "
                "qlrisk's sample snapshot valued today (override any curve, spot or vol). Example: {\"trades\": [{\"product\": "
                "\"InterestRateSwap\", \"notional\": 10000000, \"tenor_years\": 5, \"fixed_rate\": 0.044}]} returns "
                "total_npv and one row per trade."),
            input_schema=obj({**portfolio_props(limits),
                              "include_cash_flows": {"type": "boolean", "default": False}}, ["trades"]),
            handler=_price,
        ),
        ToolDef(
            name="sensitivities",
            title="Sensitivities and Greeks",
            description=(
                "Bump-and-reprice sensitivities for a book: DV01 (rates, per 1bp), CS01 (credit spreads, per 1bp), "
                "DIV01, equity/FX/commodity delta, vega, gamma (second order with central bumps), 1-day theta, "
                "key-rate ladders on native pillars or FRTB vertices, and optional cross-gamma between named factors. "
                "Results by risk class and measure, by trade, and by risk factor. Example: {\"trades\": [{\"product\": "
                "\"InterestRateSwap\", \"notional\": 10000000, \"tenor_years\": 5, \"fixed_rate\": 0.044}], "
                "\"ladder_vertices\": \"frtb_girr\"} gives the swap's DV01 and its SOFR/discount ladders."),
            input_schema=obj({
                **portfolio_props(limits),
                "risk_classes": {"type": "array", "items": {"type": "string", "enum": I.enum_values("RiskClass")},
                                 "description": "Only these risk classes (IR, CR, EQ, CM, FX, OT)."},
                "factors": {"type": "array", "items": {"type": "string"}, "description": "Only these risk-factor keys."},
                "include_theta": {"type": "boolean", "default": True},
                "include_ladders": {"type": "boolean", "default": True},
                "ladder_vertices": {"type": "string", "enum": LADDER_VERTICES, "default": "native",
                                    "description": "Ladder buckets: curve pillars, FRTB GIRR or CSR vertices, or qlrisk's standard tenors."},
                "bump_method": {"type": "string", "enum": ["central", "forward"], "default": "central",
                                "description": "central also gives gamma; forward halves the repricings."},
                "cross_gamma_factors": {"type": "array", "items": {"type": "string"},
                                        "description": f"Mixed second-order sensitivity for every pair (at most {limits.max_cross_gamma_factors} factors)."},
            }, ["trades"]),
            handler=_sens,
        ),
    ]
