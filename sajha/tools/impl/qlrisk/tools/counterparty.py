# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Counterparty credit risk: ccr_exposure, saccr, initial_margin, credit_risk and xva.

The calculator-backed measures run qlrisk's own calculators (CalculatorFactory registry, Python
implementation); their input fields and configuration keys are read from qlrisk at runtime.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .. import introspect as I
from ..inputs import InvalidInput, _coerce, build_history, build_market_data, build_trades, check_paths
from ..jsonable import rounded, to_jsonable
from . import Ctx, ToolDef, obj, portfolio_props

CREDIT = ["pd", "lgd", "ead", "el", "economic_capital", "raroc"]
EXPOSURE = ["ce", "ee", "eee", "pfe", "peak", "stressed"]
XVA_CALC = ["cva", "dva", "fva", "kva", "mva"]

# the headline number of each calculator's result
HEADLINE = {"pd": None, "lgd": None, "ead": "ead", "el": "expected_loss", "economic_capital": "economic_capital",
            "raroc": "raroc", "ce": "collateralized_ce", "ee": "ee", "eee": "effective_epe", "pfe": "pfe",
            "peak": "peak_exposure", "stressed": "stressed_exposure", "cva": "cva", "dva": "dva", "fva": "fva",
            "kva": "kva", "mva": "mva", "initial_margin": "initial_margin", "saccr": "ead"}


def _float_keys(value, tp):
    """JSON object keys are strings: turn tenor keys of Dict[float, ...] fields into numbers."""
    import typing
    from ..inputs import parse_tenor
    union = I._unwrap_optional(tp)
    if union:
        tp = union[0]
    if typing.get_origin(tp) is dict and typing.get_args(tp)[:1] == (float,) and isinstance(value, dict):
        return {parse_tenor(k): v for k, v in value.items()}
    return value


def run_calculator(measure: str, inputs: Dict[str, Any], config: Dict[str, Any], ctx: Ctx) -> Tuple[Any, List[str]]:
    import typing
    _, cls = I.calculator_class(measure)
    inp_cls = I.calculator_input_class(measure)
    if not isinstance(inputs, dict):
        raise InvalidInput(f"inputs for {measure} must be an object; fields: {I.field_summary(inp_cls)}")
    known_cfg = I.calculator_config(measure)
    unknown = set(config or {}) - set(known_cfg)
    if unknown:
        raise InvalidInput(f"config for {measure}: unknown key(s) {sorted(unknown)}; known: {sorted(known_cfg) or 'none'}")
    for k, spec in known_cfg.items():
        if k in (config or {}) and "enum" in spec and str(config[k]) not in spec["enum"]:
            raise InvalidInput(f"config.{k} must be one of {spec['enum']}")
    for where in (inputs, config or {}):
        if "num_simulations" in where:
            check_paths(where["num_simulations"], ctx.limits, f"{measure} num_simulations")
    cfg = dict(config or {})
    if measure in ("ee", "eee", "pfe", "peak", "economic_capital"):
        sims = int(inputs.get("num_simulations", cfg.get("num_simulations", min(10_000, ctx.limits.max_mc_paths))))
        cfg["num_simulations"] = check_paths(sims, ctx.limits, f"{measure} num_simulations")
    if measure == "eee":
        cfg["calculate_effective"] = True
    hints = typing.get_type_hints(inp_cls)
    data = {k: _float_keys(v, hints.get(k)) for k, v in inputs.items()}
    names = set(hints)
    bad = set(data) - names
    if bad:
        raise InvalidInput(f"inputs for {measure}: unknown field(s) {sorted(bad)}; fields: {I.field_summary(inp_cls)}")
    try:
        typed = _coerce(data, inp_cls, f"inputs ({measure})")
    except TypeError as exc:
        raise InvalidInput(f"inputs for {measure}: {exc}; fields: {I.field_summary(inp_cls)}") from None
    try:
        res = cls(f"mcp_{measure}", cfg).calculate(typed)
    except (ValueError, ZeroDivisionError, KeyError) as exc:
        raise InvalidInput(f"{measure}: qlrisk rejected the inputs: {type(exc).__name__}: {exc}") from None
    return to_jsonable(res.value), list(res.warnings or [])


def _headline(measure: str, value: Any) -> Any:
    key = HEADLINE.get(measure)
    if key is None or not isinstance(value, dict):
        return value
    return value.get(key)


def _calc_tool_result(measure: str, value: Any, warnings: List[str], label: str):
    head = _headline(measure, value)
    out = {"measure": measure, "result": value, "headline": head}
    if warnings:
        out["warnings"] = warnings
    shown = f"{head:.6g}" if measure in ("pd", "lgd") and isinstance(head, (int, float)) else rounded(head)
    return out, f"{label}: {shown}"


def _ccr(args: Dict[str, Any], ctx: Ctx):
    mode = args.get("mode", "calculator" if args.get("measure") else "trade_profiles")
    if mode == "calculator":
        m = args.get("measure")
        if m not in EXPOSURE:
            raise InvalidInput(f"calculator mode needs measure, one of {EXPOSURE}")
        value, warns = run_calculator(m, args.get("inputs") or {}, args.get("config") or {}, ctx)
        if m == "eee" and isinstance(value, dict):
            value = {k: v for k, v in value.items() if k in ("eee_profile", "effective_epe", "epe", "ee_profile", "time_points", "time_grid", "components") or "eff" in k}
        return _calc_tool_result(m, value, warns, m.upper())
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"))
    trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
    if mode == "wrong_way":
        from qlrisk.scenarios import wrong_way_exposure
        if not args.get("credit_factor"):
            raise InvalidInput("wrong_way needs credit_factor, the counterparty's credit-spread factor (e.g. 'CR.GLOBEX.5Y')")
        hist = build_history(args.get("history"), md, ctx.limits)
        r = wrong_way_exposure(trades, md, hist, args["credit_factor"], shock_sigmas=float(args.get("shock_sigmas", 3.0)),
                               horizon_days=int(args.get("horizon_days", 10)), lookback=args.get("lookback"),
                               reporting_currency=ccy, top_n=int(args.get("top_n", 5)))
        out = {"mode": mode, "reporting_currency": ccy, "credit_factor": args["credit_factor"], "base_exposure": r.base_exposure,
               "conditional_exposure": r.conditional_exposure, "ratio": r.ratio, "spread_move": r.spread_move,
               "top_moves": {str(k): v for k, v in r.top_moves.items()}}
        return out, (f"Wrong-way risk: exposure {rounded(r.base_exposure)} -> {rounded(r.conditional_exposure)} {ccy} "
                     f"when {args['credit_factor']} widens {args.get('shock_sigmas', 3.0)} sigma (ratio {r.ratio:.2f})")
    if mode != "trade_profiles":
        raise InvalidInput("mode must be trade_profiles, calculator or wrong_way")
    n = check_paths(args.get("num_scenarios", 2000), ctx.limits, "num_scenarios")
    rows = []
    for t in trades:
        try:
            p = t.calculate_ccr_exposure(md, time_horizon=float(args.get("time_horizon", 5.0)), num_scenarios=n,
                                         confidence_level=float(args.get("confidence_level", 0.95)))
        except Exception as exc:
            rows.append({"trade_id": t.trade_id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append({"trade_id": t.trade_id, "product": type(t).__name__, "currency": t.currency.value,
                     "time_grid": to_jsonable(p.time_grid), "expected_exposure": to_jsonable(p.expected_exposure),
                     "potential_future_exposure": to_jsonable(p.potential_future_exposure),
                     "effective_ee": to_jsonable(p.effective_ee), "peak_exposure": p.peak_exposure, "epe": p.epe,
                     "effective_epe": p.effective_epe, "cva": p.cva})
    ok = [r for r in rows if "error" not in r]
    peak = max((r["peak_exposure"] for r in ok), default=0.0)
    return {"mode": mode, "num_scenarios": n, "trades": rows}, \
        f"Exposure profiles for {len(ok)} trade(s); largest peak PFE {rounded(peak)}"


def _saccr(args: Dict[str, Any], ctx: Ctx):
    mode = args.get("mode", "netting_sets")
    if mode == "calculator":
        value, warns = run_calculator("saccr", args.get("calculator_input") or {}, {}, ctx)
        return _calc_tool_result("saccr", value, warns, "SA-CCR EAD (calculator)")
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"))
    trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
    if mode == "trades":
        rows = []
        for t in trades:
            try:
                rows.append({"trade_id": t.trade_id, **to_jsonable(t.calculate_saccr(md))})
            except Exception as exc:
                rows.append({"trade_id": t.trade_id, "error": f"{type(exc).__name__}: {exc}"})
        total = sum(r.get("ead", 0.0) for r in rows)
        return {"mode": mode, "trades": rows, "ead_sum": total}, f"SA-CCR trade-level EAD sum {rounded(total)} (no netting)"
    if mode != "netting_sets":
        raise InvalidInput("mode must be netting_sets, trades or calculator")
    from qlrisk.regulatory.saccr_netting import CSATerms, saccr_netting_sets
    csa = {ns: _coerce(v, CSATerms, f"csa.{ns}") for ns, v in (args.get("csa") or {}).items()}
    sets = saccr_netting_sets(trades, md, ccy, csa or None, args.get("index_names") or ())
    rows = {ns: to_jsonable(s) for ns, s in sets.items()}
    total = sum(s.ead for s in sets.values())
    return {"mode": mode, "reporting_currency": ccy, "netting_sets": rows, "ead_total": total}, \
        f"SA-CCR EAD {rounded(total)} {ccy} across {len(sets)} netting set(s)"


def _im(args: Dict[str, Any], ctx: Ctx):
    positions = args.get("positions") or []
    if not positions:
        raise InvalidInput("positions: send at least one position (notional, product_type, remaining_maturity ...)")
    cfg = {k: args[k] for k in ("method", "confidence_level", "mpor_scaling") if k in args}
    cfg.setdefault("method", "simm")
    if len(positions) == 1:
        value, warns = run_calculator("initial_margin", positions[0], cfg, ctx)
        return _calc_tool_result("initial_margin", value, warns, f"Initial margin ({cfg['method']})")
    import typing
    _, cls = I.calculator_class("initial_margin")
    inp = I.calculator_input_class("initial_margin")
    typed = []
    for i, p in enumerate(positions):
        bad = set(p) - set(typing.get_type_hints(inp))
        if bad:
            raise InvalidInput(f"positions[{i}]: unknown field(s) {sorted(bad)}; fields: {I.field_summary(inp)}")
        try:
            typed.append(_coerce(p, inp, f"positions[{i}]"))
        except TypeError as exc:
            raise InvalidInput(f"positions[{i}]: {exc}") from None
    r = to_jsonable(cls("mcp_im", cfg).calculate_portfolio_im(typed))
    return {"measure": "initial_margin", "method": cfg["method"], "result": r, "headline": r.get("initial_margin")}, \
        f"Portfolio initial margin ({cfg['method']}): {rounded(r.get('initial_margin'))} over {len(typed)} positions"


def _credit(args: Dict[str, Any], ctx: Ctx):
    m = args["measure"]
    value, warns = run_calculator(m, args.get("inputs") or {}, args.get("config") or {}, ctx)
    return _calc_tool_result(m, value, warns, m.upper().replace("_", " "))


def _xva(args: Dict[str, Any], ctx: Ctx):
    m = args["measure"]
    if m in XVA_CALC:
        value, warns = run_calculator(m, args.get("inputs") or {}, args.get("config") or {}, ctx)
        return _calc_tool_result(m, value, warns, m.upper())
    if m == "total":
        from qlrisk.calculator.python.xva_calculators import TotalXVAResult
        parts = args.get("inputs") or {}
        unknown = set(parts) - set(XVA_CALC) - {"colva"}
        if unknown:
            raise InvalidInput(f"total: inputs keys are {XVA_CALC + ['colva']}; unknown {sorted(unknown)}")
        res, details = TotalXVAResult(), {}
        for name in XVA_CALC:
            if name in parts:
                value, _ = run_calculator(name, parts[name], (args.get("config") or {}).get(name, {}), ctx)
                details[name] = value
                setattr(res, name, float(_headline(name, value) or 0.0))
        res.colva = float(parts.get("colva", 0.0))
        res.calculate_total()
        out = {"measure": m, "components": to_jsonable(res), "details": details,
               "convention": "total_xva = cva + dva + fva + kva + mva + colva, each as qlrisk's calculator reports it; "
                             "colva is the figure you supplied (qlrisk has no ColVA calculator)"}
        return out, f"Total XVA {rounded(res.total_xva)} (" + ", ".join(f"{k.upper()} {rounded(getattr(res, k))}" for k in XVA_CALC + ["colva"]) + ")"
    if m == "sa_cva":
        from qlrisk.regulatory.sa_cva import cva_from_profile, sa_cva_capital
        need = [k for k in ("counterparty", "time_grid", "expected_exposure", "counterparty_buckets") if not args.get(k)]
        if need:
            raise InvalidInput(f"sa_cva needs {need}")
        if len(args["time_grid"]) != len(args["expected_exposure"]):
            raise InvalidInput("time_grid and expected_exposure must have the same length")
        ccy = args.get("reporting_currency", "USD")
        md = build_market_data(args.get("market_data"))
        if args["counterparty"] not in md.credit_curves:
            raise InvalidInput(f"counterparty {args['counterparty']!r} has no credit curve in the market data "
                               f"(have {sorted(md.credit_curves)}); add market_data.credit_curves")
        hedges = build_trades(args["hedges"], md, ctx.limits, ctx.warnings) if args.get("hedges") else []
        fn = cva_from_profile(args["counterparty"], args["time_grid"], args["expected_exposure"], float(args.get("recovery", 0.4)))
        buckets = {k: (str(v[0]), bool(v[1])) for k, v in args["counterparty_buckets"].items()}
        kw = {k: args[k] for k in ("reference_buckets", "equity_buckets", "commodity_buckets", "curve_currency") if k in args}
        r = sa_cva_capital(fn, md, buckets, hedges=hedges, m_cva=float(args.get("m_cva", 1.0)), reporting_currency=ccy, **kw)
        out = {"measure": m, "reporting_currency": ccy, "cva": fn(md), "capital": r.total,
               "by_component": to_jsonable(r.by_component), "by_bucket": to_jsonable(r.by_bucket),
               "sensitivities": len(r.sensitivities)}
        return out, f"SA-CVA capital {rounded(r.total)} {ccy} (CVA {rounded(out['cva'])}, {len(hedges)} hedge(s))"
    if m == "ba_cva":
        from qlrisk.regulatory import CVACounterparty, CVAIndexHedge, ba_cva
        cps = args.get("counterparties")
        if not cps:
            raise InvalidInput("ba_cva needs counterparties: [{name, sector, investment_grade, netting_sets: [[ead, maturity]], hedges}]")
        parsed = [_coerce(c, CVACounterparty, f"counterparties[{i}]") for i, c in enumerate(cps)]
        sectors = I.ba_cva_sectors()
        for c in parsed:
            if c.sector not in sectors:
                raise InvalidInput(f"counterparty {c.name}: sector {c.sector!r} is not one of {sectors}")
        idx = [_coerce(h, CVAIndexHedge, f"index_hedges[{i}]") for i, h in enumerate(args.get("index_hedges") or [])]
        r = ba_cva(parsed, idx)
        return {"measure": m, "result": to_jsonable(r)}, f"BA-CVA capital {rounded(r.get('capital'))}"
    raise InvalidInput("measure must be one of cva, dva, fva, kva, mva, total, sa_cva, ba_cva")


def _measure_doc(measures: List[str]) -> str:
    return " ".join(f"{m}: {I.field_summary(I.calculator_input_class(m))}." for m in measures)


def _config_doc(measures: List[str]) -> str:
    parts = []
    for m in measures:
        c = I.calculator_config(m)
        if c:
            parts.append(f"{m}: " + ", ".join(f"{k}" + (f" ({'|'.join(v['enum'])})" if "enum" in v else "") for k, v in c.items()))
    return "; ".join(parts)


def tools(limits) -> List[ToolDef]:
    from qlrisk.regulatory import CVACounterparty, CVAIndexHedge
    from qlrisk.regulatory.saccr_netting import CSATerms
    im_cfg = I.calculator_config("initial_margin")
    im_schema = I.dataclass_schema(I.calculator_input_class("initial_margin"))
    cp_schema = I.dataclass_schema(CVACounterparty)
    cp_schema["properties"]["sector"] = {"type": "string", "enum": I.ba_cva_sectors(), "default": "other"}
    cp_schema["properties"]["netting_sets"] = {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                                               "description": "[EAD, effective maturity in years] per netting set."}
    return [
        ToolDef(
            name="ccr_exposure",
            title="Counterparty exposure",
            description=(
                "Counterparty credit exposure. mode='trade_profiles' simulates each trade's exposure profile from the "
                "market data: EE, PFE, effective EE (EEE), EPE, effective EPE, peak PFE and a CVA estimate. "
                "mode='calculator' runs a qlrisk exposure calculator from summary inputs: measure ce (current exposure, "
                "collateral-adjusted), ee, eee, pfe, peak, stressed (crisis scenarios). mode='wrong_way' measures wrong-way "
                "risk: exposure conditional on the counterparty's credit spread widening by shock_sigmas. Calculator fields: "
                + _measure_doc(EXPOSURE) + " Config: " + _config_doc(EXPOSURE) + ". Example: {\"mode\": \"calculator\", "
                "\"measure\": \"pfe\", \"inputs\": {\"current_mtm\": 100000, \"notional\": 10000000, \"remaining_maturity\": 5, "
                "\"volatility\": 0.01}}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "mode": {"type": "string", "enum": ["trade_profiles", "calculator", "wrong_way"]},
                "measure": {"type": "string", "enum": EXPOSURE},
                "inputs": {"type": "object", "description": "calculator: the measure's input fields (see description)."},
                "config": {"type": "object", "description": "calculator: the measure's configuration (see description)."},
                "time_horizon": {"type": "number", "exclusiveMinimum": 0, "default": 5.0},
                "num_scenarios": {"type": "integer", "minimum": 100, "maximum": limits.max_mc_paths, "default": 2000},
                "confidence_level": {"type": "number", "default": 0.95},
                "credit_factor": {"type": "string", "description": "wrong_way: credit-spread factor key, e.g. 'CR.GLOBEX.5Y'."},
                "shock_sigmas": {"type": "number", "default": 3.0},
                "horizon_days": {"type": "integer", "default": 10},
                "lookback": {"type": "integer"},
                "top_n": {"type": "integer", "default": 5},
            }),
            handler=_ccr,
        ),
        ToolDef(
            name="saccr",
            title="SA-CCR exposure at default",
            description=(
                "Basel SA-CCR (CRE52) exposure at default. mode='netting_sets' (default) nets the book per netting set with "
                "hedging-set aggregation (IR by currency and maturity bucket, FX by pair, credit / equity by entity, "
                "commodity by type), replacement cost, PFE multiplier and alpha 1.4; csa gives each set's margining and "
                "collateral. mode='trades' gives each trade's stand-alone RC, add-on and EAD. mode='calculator' runs "
                "qlrisk's SA-CCR calculator on trade summaries (" + I.field_summary(I.calculator_input_class("saccr")) + "). "
                "Example: {\"trades\": [{\"product\": \"InterestRateSwap\", \"notional\": 10000000, \"tenor_years\": 5, "
                "\"fixed_rate\": 0.044, \"counterparty_id\": \"BANK-A\"}], \"csa\": {\"BANK-A\": {\"margined\": true, "
                "\"threshold\": 0}}}."),
            input_schema=obj({
                **portfolio_props(limits),
                "mode": {"type": "string", "enum": ["netting_sets", "trades", "calculator"], "default": "netting_sets"},
                "csa": {"type": "object", "additionalProperties": I.dataclass_schema(CSATerms),
                        "description": "Netting set id (default: counterparty_id) -> CSA terms."},
                "index_names": {"type": "array", "items": {"type": "string"}, "description": "Credit / equity names that are indices (80% correlation)."},
                "calculator_input": {"type": "object", "description": "calculator: SACCRInput fields."},
            }),
            handler=_saccr,
        ),
        ToolDef(
            name="initial_margin",
            title="Initial margin (ISDA SIMM)",
            description=(
                "Initial margin with qlrisk's IM calculator: method 'simm' (ISDA SIMM delta / vega / curvature margin by "
                "risk class, MPOR scaling), 'schedule' (BCBS-IOSCO grid by product and maturity, net-to-gross adjusted) or "
                "'var'. One position gives its IM; several give the portfolio IM with netting across positions. Position "
                "fields: " + I.field_summary(I.calculator_input_class("initial_margin")) + ". Example: {\"method\": \"simm\", "
                "\"positions\": [{\"notional\": 10000000, \"product_type\": \"irs\", \"remaining_maturity\": 5, "
                "\"delta_sensitivities\": {\"USD-5Y\": 4500}}]}."),
            input_schema=obj({
                "positions": {"type": "array", "items": im_schema, "minItems": 1, "maxItems": limits.max_trades},
                "method": {**im_cfg.get("method", {"type": "string"}), "default": "simm"},
                "confidence_level": im_cfg.get("confidence_level", {"type": "number"}),
                "mpor_scaling": im_cfg.get("mpor_scaling", {"type": "boolean"}),
            }, ["positions"]),
            handler=_im,
        ),
        ToolDef(
            name="credit_risk",
            title="Credit risk measures",
            description=(
                "Credit-risk calculators: pd (probability of default: structural Merton, reduced form, rating transition "
                "matrix, logistic, historical), lgd (fixed, collateral, workout, market, stochastic), ead, el (expected loss "
                "= PD x LGD x EAD), economic_capital (Vasicek, Gordy, Monte Carlo; also EL, VaR and ES of the loss "
                "distribution) and raroc (risk-adjusted return on capital vs a hurdle). Fields per measure: "
                + _measure_doc(CREDIT) + " Config: " + _config_doc(CREDIT) + ". Example: {\"measure\": \"pd\", \"inputs\": "
                "{\"credit_rating\": \"BBB\"}, \"config\": {\"model\": \"transition_matrix\"}}."),
            input_schema=obj({
                "measure": {"type": "string", "enum": CREDIT},
                "inputs": {"type": "object", "description": "The measure's input fields (see description)."},
                "config": {"type": "object", "description": "The measure's configuration (see description)."},
            }, ["measure", "inputs"]),
            handler=_credit,
        ),
        ToolDef(
            name="xva",
            title="XVA and CVA capital",
            description=(
                "Valuation adjustments and CVA capital. measure cva (unilateral or bilateral, analytic or Monte Carlo, "
                "optional wrong-way), dva, fva, kva, mva run qlrisk's calculators on an exposure profile; 'total' runs any "
                "of them together (inputs: {cva: {...}, dva: {...}, ..., colva: number}) and sums them; 'sa_cva' is the "
                "MAR50 standardised CVA capital from an expected-exposure profile and the counterparty's credit curve, with "
                "optional hedge trades; 'ba_cva' is the basic approach (reduced, or full with hedges). Fields: "
                + _measure_doc(XVA_CALC) + " Config: " + _config_doc(XVA_CALC) + ". Example: {\"measure\": \"cva\", \"inputs\": "
                "{\"ee_profile\": [2e6, 3e6, 3.5e6, 3e6, 2e6, 1e6], \"time_grid\": [0.5, 1, 2, 3, 4, 5], \"credit_spread\": 0.012}}."),
            input_schema=obj({
                "measure": {"type": "string", "enum": XVA_CALC + ["total", "sa_cva", "ba_cva"]},
                "inputs": {"type": "object", "description": "cva / dva / fva / kva / mva: the calculator's fields; total: one object per adjustment plus colva."},
                "config": {"type": "object"},
                "market_data": portfolio_props(limits)["market_data"],
                "reporting_currency": portfolio_props(limits)["reporting_currency"],
                "counterparty": {"type": "string", "description": "sa_cva: credit-curve name of the counterparty (e.g. 'ACME')."},
                "time_grid": {"type": "array", "items": {"type": "number"}},
                "expected_exposure": {"type": "array", "items": {"type": "number"}},
                "recovery": {"type": "number", "default": 0.4},
                "counterparty_buckets": {"type": "object", "additionalProperties": {"type": "array", "prefixItems": [{"type": "string"}, {"type": "boolean"}], "minItems": 2, "maxItems": 2},
                                         "description": "sa_cva: credit-curve name -> [MAR50 bucket '1a'...'8', investment grade?]."},
                "hedges": {**portfolio_props(limits)["trades"], "description": "sa_cva: eligible hedge trades (e.g. a CDS on the counterparty)."},
                "m_cva": {"type": "number", "default": 1.0},
                "reference_buckets": {"type": "object", "additionalProperties": {"type": "integer"}},
                "counterparties": {"type": "array", "items": cp_schema},
                "index_hedges": {"type": "array", "items": I.dataclass_schema(CVAIndexHedge)},
            }, ["measure"]),
            handler=_xva,
        ),
    ]
