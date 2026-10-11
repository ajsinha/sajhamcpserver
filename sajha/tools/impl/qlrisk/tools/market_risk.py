# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""value_at_risk, backtest, pnl_explain and stress_test: market risk on a book."""

from __future__ import annotations

from typing import Any, Dict, List

from .. import introspect as I
from ..inputs import (InvalidInput, apply_shock_list, build_history, build_market_data, build_trades, check_paths,
                      parse_date, pv_in, shock_schema)
from ..jsonable import rounded, to_jsonable
from . import Ctx, ToolDef, obj, portfolio_props

# the liquidity object in qlrisk's terms; the presented one (spreads_bp) comes from generate.LIQUIDITY
LIQUIDITY_Q = {"type": "object", "properties": {"spreads": {"type": "object", "additionalProperties": {"type": "number"}},
                                                "horizon_days": {"type": "integer", "minimum": 1, "default": 1}},
               "required": ["spreads"]}
VAR_METHODS = ["historical", "age_weighted", "filtered_historical", "monte_carlo", "parametric"]


def _engine(ccy):
    from qlrisk.engine import MarketRiskEngine
    return MarketRiskEngine(reporting_currency=ccy)


def _measure(r) -> Dict[str, Any]:
    d = to_jsonable(r)
    d["tail_scenarios"] = d.get("tail_scenarios", [])[:10]
    return d


def _check_conf(x, what):
    if not 0.5 <= float(x) < 1.0:
        raise InvalidInput(f"{what} must be in [0.5, 1), e.g. 0.99")
    return float(x)


def _var(args: Dict[str, Any], ctx: Ctx):
    conf = _check_conf(args.get("confidence", 0.99), "confidence")
    esc = _check_conf(args.get("es_confidence", 0.975), "es_confidence")
    horizon = int(args.get("horizon_days", 1))
    if not 1 <= horizon <= 250:
        raise InvalidInput("horizon_days must be between 1 and 250")
    if args.get("mode", "portfolio") == "pnl_series":
        from qlrisk.calculator.python.var_calculators import expected_shortfall, scale_to_horizon, value_at_risk
        pnl = args.get("pnl")
        if not pnl or len(pnl) < 10:
            raise InvalidInput("pnl_series mode needs 'pnl' with at least 10 P&L observations (gains positive)")
        w = args.get("weights")
        if w is not None and len(w) != len(pnl):
            raise InvalidInput("weights must have one entry per P&L observation")
        var1, es1 = value_at_risk(pnl, conf, w), expected_shortfall(pnl, esc, w)
        out = {"mode": "pnl_series", "n": len(pnl), "confidence": conf, "es_confidence": esc, "horizon_days": horizon,
               "var": scale_to_horizon(var1, 1, horizon), "es": scale_to_horizon(es1, 1, horizon),
               "var_1d": var1, "es_1d": es1}
        return out, f"VaR {conf:.1%} {horizon}d {rounded(out['var'])}; ES {esc:.1%} {rounded(out['es'])} from {len(pnl)} P&L observations"

    from qlrisk.scenarios import (filtered_historical_scenarios, historical_scenarios, monte_carlo_scenarios)
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"), None, ctx.warnings)
    trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
    hist = build_history(args.get("history"), md, ctx.limits)
    lookback = int(args.get("lookback", 250))
    if lookback + horizon >= len(hist):
        raise InvalidInput(f"lookback {lookback} + horizon {horizon} needs a longer history than {len(hist)} days")
    eng = _engine(ccy)
    method = args.get("method", "historical")
    reval = args.get("revaluation", "full")
    sens = eng.sensitivities(trades, md) if reval == "taylor" or method == "parametric" else None
    out: Dict[str, Any] = {"mode": "portfolio", "method": method, "revaluation": reval, "reporting_currency": ccy,
                           "valuation_date": md.valuation_date.isoformat(), "confidence": conf, "es_confidence": esc,
                           "horizon_days": horizon, "lookback": lookback, "history_days": len(hist)}
    if method == "parametric":
        ewma = args.get("ewma_lambda")
        var = eng.parametric_var(trades, md, hist, conf, horizon, lookback, ewma, "var", sensitivities=sens)
        es = eng.parametric_var(trades, md, hist, esc, horizon, lookback, ewma, "es", sensitivities=sens)
        out["var"], out["es"] = _measure(var), _measure(es)
    else:
        if method == "historical":
            scen = historical_scenarios(hist, lookback=lookback, horizon=horizon)
        elif method == "age_weighted":
            scen = historical_scenarios(hist, lookback=lookback, horizon=horizon, age_weighting=float(args.get("age_decay", 0.98)))
        elif method == "filtered_historical":
            scen = filtered_historical_scenarios(hist, ewma_lambda=float(args.get("ewma_lambda", 0.94)), lookback=lookback, horizon=horizon)
        elif method == "monte_carlo":
            n = check_paths(args.get("mc_paths", 5000), ctx.limits, "mc_paths")
            dist = {"normal": "normal", "student_t": "t"}[args.get("mc_distribution", "normal")]
            scen = monte_carlo_scenarios(hist, n=n, horizon=horizon, lookback=lookback, ewma_lambda=args.get("ewma_lambda"),
                                         distribution=dist, dof=float(args.get("mc_dof", 5.0)), seed=args.get("seed", 7))
        else:
            raise InvalidInput(f"method must be one of {VAR_METHODS}")
        pnl = eng.scenario_pnl(trades, md, scen, method=reval, sensitivities=sens)
        out["var"], out["es"] = _measure(pnl.var(conf)), _measure(pnl.es(esc))
        if args.get("decomposition", True):
            out["decomposition"] = {"component": to_jsonable(pnl.var(conf).contributions),
                                    "incremental": to_jsonable(pnl.incremental(conf)),
                                    "standalone": to_jsonable(pnl.standalone(conf))}
            if args.get("group_by"):
                g = pnl.group(args["group_by"])
                out["decomposition"]["by_group"] = to_jsonable(g.var(conf).contributions)
        if pnl.errors:
            out["pricing_errors"] = to_jsonable(pnl.errors[:20])
    if args.get("include_stressed_var"):
        svh = int(args.get("svar_horizon_days", 10))
        window = int(args.get("stress_window", 250))
        if window >= len(hist):
            raise InvalidInput(f"stress_window {window} needs a history longer than {len(hist)} days")
        out["stressed_var"] = _measure(eng.stressed_var(trades, md, hist, window, conf, svh))
    liq = args.get("liquidity")
    if liq:
        from qlrisk.calculator.python.liquidity_var import liquidity_adjusted_var, liquidity_cost
        from ..units import liquidity_to_qlrisk, note_received
        values = {t.trade_id: pv_in(t, md, ccy)[2] for t in trades}
        q_liq = liquidity_to_qlrisk(liq, LIQUIDITY_Q, "liquidity", ctx.warnings)
        spreads = {k: float(v) for k, v in (q_liq.get("spreads") or {}).items()}
        unknown = set(spreads) - set(values)
        if unknown:
            raise InvalidInput(f"liquidity.spreads_bp: unknown trade ids {sorted(unknown)}")
        note_received("liquidity", q_liq)
        lh = int(q_liq.get("horizon_days", 1))
        out["liquidity"] = {"liquidation_cost": liquidity_cost(values, spreads), "horizon_days": lh,
                            "liquidity_adjusted_var": liquidity_adjusted_var(out["var"]["value"], values, spreads, lh)}
    s = f"{method} VaR {conf:.1%} {horizon}d {rounded(out['var']['value'])} {ccy}; ES {esc:.1%} {rounded(out['es']['value'])}"
    if "stressed_var" in out:
        s += f"; SVaR {rounded(out['stressed_var']['value'])}"
    return out, s


def _backtest(args: Dict[str, Any], ctx: Ctx):
    mode = args.get("mode", "portfolio")
    conf = _check_conf(args.get("confidence", 0.99), "confidence")
    esc = _check_conf(args.get("es_confidence", 0.975), "es_confidence")

    def var_result(r):
        d = to_jsonable(r)
        d.pop("hits", None)
        return d

    if mode == "var_series":
        from qlrisk.backtesting import backtest_var
        pnl, fc = args.get("pnl"), args.get("var_forecasts")
        if not pnl or not fc or len(pnl) != len(fc):
            raise InvalidInput("var_series needs 'pnl' and 'var_forecasts' of the same length (VaR as positive losses)")
        r = backtest_var(pnl, fc, conf, args.get("labels"))
        return {"mode": mode, "var": var_result(r)}, f"VaR backtest: {r.exceptions} exceptions in {r.n} days, {r.zone} zone, multiplier {r.multiplier}"
    if mode == "es_series":
        from qlrisk.backtesting import backtest_es
        pnl, fc, es = args.get("pnl"), args.get("var_forecasts"), args.get("es_forecasts")
        if not pnl or not fc or not es or not len(pnl) == len(fc) == len(es):
            raise InvalidInput("es_series needs 'pnl', 'var_forecasts' and 'es_forecasts' of the same length")
        r = backtest_es(pnl, fc, es, esc)
        return {"mode": mode, "es": to_jsonable(r)}, f"ES backtest (Acerbi-Szekely): Z2 {r.z2:.3f}, {r.zone} zone"
    if mode == "pla":
        from qlrisk.pnl import pla_test
        hpl, rtpl = args.get("hpl"), args.get("rtpl")
        if not hpl or not rtpl or len(hpl) != len(rtpl):
            raise InvalidInput("pla needs 'hpl' and 'rtpl' of the same length")
        r = pla_test(hpl, rtpl)
        return {"mode": mode, "pla": to_jsonable(r)}, f"PLA test: Spearman {r.spearman:.3f}, KS {r.ks_statistic:.3f}, {r.zone} zone"
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"), None, ctx.warnings)
    trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
    hist = build_history(args.get("history"), md, ctx.limits)
    test_days, lookback = int(args.get("test_days", 250)), int(args.get("lookback", 250))
    if test_days + lookback + 2 > len(hist):
        raise InvalidInput(f"test_days {test_days} + lookback {lookback} needs a history of at least {test_days + lookback + 2} days")
    bt = _engine(ccy).backtest(trades, md, hist, test_days=test_days, lookback=lookback, confidence=conf, es_confidence=esc)
    out = {"mode": mode, "reporting_currency": ccy, "var": var_result(bt["var"]), "es": to_jsonable(bt["es"]),
           "pla": to_jsonable(bt["pla"])}
    if args.get("include_series"):
        out["series"] = to_jsonable(bt["series"])
    v = bt["var"]
    return out, (f"Backtest over {v.n} days: {v.exceptions} VaR exceptions ({v.zone}, multiplier {v.multiplier}); "
                 f"ES {bt['es'].zone}; PLA {bt['pla'].zone}")


def _explain(args: Dict[str, Any], ctx: Ctx):
    ccy = args.get("reporting_currency", "USD")
    md0 = build_market_data(args.get("market_data"), None, ctx.warnings)
    trades = build_trades(args["trades"], md0, ctx.limits, ctx.warnings)
    if args.get("end_market_data"):
        md1 = build_market_data(args["end_market_data"], md0.valuation_date, ctx.warnings, "end_market_data")
    else:
        if not args.get("end_shocks") and not args.get("end_valuation_date"):
            raise InvalidInput("give end_market_data, or end_shocks and/or end_valuation_date, to define the end of the period")
        md1 = apply_shock_list(md0, args.get("end_shocks") or [], "end_shocks", ctx.warnings)
        if md1 is md0:
            import copy
            md1 = copy.deepcopy(md0)
    if args.get("end_valuation_date"):
        md1.valuation_date = parse_date(args["end_valuation_date"], "end_valuation_date")
    if md1.valuation_date < md0.valuation_date:
        raise InvalidInput("the end valuation date is before the start")
    ex = _engine(ccy).explain(trades, md0, md1)
    total = ex.total()
    rows = []
    for tid, te in ex.trades.items():
        explained = te.theta + sum(te.by_risk_class.values())
        rows.append({"trade_id": tid, "actual": te.actual, "theta": te.theta, "by_risk_class": to_jsonable(te.by_risk_class),
                     "unexplained": te.actual - explained,
                     "top_factors": {str(k): v for k, v in sorted(te.by_factor.items(), key=lambda kv: -abs(kv[1]))[:10]}})
    out = {"reporting_currency": ccy, "start": md0.valuation_date.isoformat(), "end": md1.valuation_date.isoformat(),
           "total": to_jsonable(total), "trades": rows}
    return out, (f"P&L {md0.valuation_date} -> {md1.valuation_date}: actual {rounded(total.get('actual'))} {ccy}, "
                 f"theta {rounded(total.get('theta'))}, unexplained {rounded(total.get('unexplained'))}")


def _stress(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.scenarios import STRESS_LIBRARY, StressDefinition, historical_stress_scenarios, stress_shocks
    from ..units import human_shock, note_received, stress_definition_to_qlrisk
    mode = args.get("mode", "library")
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"), None, ctx.warnings)
    trades = build_trades(args["trades"], md, ctx.limits, ctx.warnings)
    eng = _engine(ccy)
    if mode == "reverse":
        from qlrisk.scenarios import reverse_stress_test
        if "target_loss" not in args or float(args["target_loss"]) <= 0:
            raise InvalidInput("reverse mode needs target_loss, a positive loss amount in the reporting currency")
        hist = build_history(args.get("history"), md, ctx.limits)
        r = reverse_stress_test(trades, md, hist, float(args["target_loss"]), lookback=int(args.get("lookback", 250)),
                                reporting_currency=ccy, top_n=int(args.get("top_n", 10)))
        out = {"mode": mode, "reporting_currency": ccy, "target_loss": r.target_loss, "achieved_loss": r.achieved_loss,
               "scale": r.scale, "sigma_distance": r.sigma_distance,
               "top_moves": {str(k): v for k, v in r.top_moves.items()},
               "shocks": [human_shock(s) for s in sorted(r.shocks, key=lambda s: -abs(s.size))[: int(args.get("top_n", 10))]]}
        return out, (f"Reverse stress: a loss of {rounded(r.achieved_loss)} {ccy} is {r.sigma_distance:.2f} sigma away "
                     f"(most plausible scenario, scale {r.scale:.2f})")
    base = {t.trade_id: pv_in(t, md, ccy)[2] for t in trades}
    results = []
    if mode == "library":
        names = args.get("scenarios") or list(STRESS_LIBRARY)
        unknown = [n for n in names if n not in STRESS_LIBRARY]
        if unknown:
            raise InvalidInput(f"scenarios: unknown {unknown}; choose from {list(STRESS_LIBRARY)}")
        scen = historical_stress_scenarios(md, names)
        pnl = eng.scenario_pnl(trades, md, scen)
        for j, label in enumerate(pnl.labels):
            results.append({"scenario": str(label), "description": STRESS_LIBRARY[str(label)].description,
                            "pnl": float(pnl.portfolio[j]),
                            "by_trade": {tid: float(pnl.values[i, j]) for i, tid in enumerate(pnl.trade_ids)}})
    elif mode == "custom":
        items = args.get("custom_scenarios") or []
        if not items:
            raise InvalidInput("custom mode needs custom_scenarios: [{name, shocks: [...]} or {name, definition: {...}}]")
        for i, sc in enumerate(items):
            name = sc.get("name") or f"scenario_{i + 1}"
            if sc.get("definition") and sc.get("shocks"):
                raise InvalidInput(f"custom_scenarios[{i}]: give 'shocks' or 'definition', not both")
            if sc.get("definition"):
                where = f"custom_scenarios[{i}].definition"
                d = stress_definition_to_qlrisk(sc["definition"], where, ctx.warnings)
                try:
                    sdef = StressDefinition(name=name, description=d.pop("description", name), **d)
                except TypeError as exc:
                    raise InvalidInput(f"{where}: {exc}") from None
                note_received(where, {k: (list(v) if isinstance(v, tuple) else v) for k, v in vars(sdef).items()})
                from qlrisk.riskfactors import apply_shocks
                md_s = apply_shocks(md, stress_shocks(md, sdef))
            elif sc.get("shocks"):
                md_s = apply_shock_list(md, sc["shocks"], f"custom_scenarios[{i}].shocks", ctx.warnings)
            else:
                raise InvalidInput(f"custom_scenarios[{i}] needs 'shocks' or 'definition'")
            by_trade = {t.trade_id: pv_in(t, md_s, ccy)[2] - base[t.trade_id] for t in trades}
            results.append({"scenario": name, "pnl": sum(by_trade.values()), "by_trade": by_trade})
    else:
        raise InvalidInput("mode must be library, custom or reverse")
    results.sort(key=lambda r: r["pnl"])
    worst = results[0]
    out = {"mode": mode, "reporting_currency": ccy, "base_pv": base, "results": results, "worst": worst["scenario"]}
    return out, f"{len(results)} stress scenario(s); worst {worst['scenario']} P&L {rounded(worst['pnl'])} {ccy}"


def tools(limits) -> List[ToolDef]:
    lib = list(I.stress_library())
    conf = {"type": "number", "minimum": 0.5, "exclusiveMaximum": 1, "default": 0.99}
    esc = {"type": "number", "minimum": 0.5, "exclusiveMaximum": 1, "default": 0.975}
    series = {"type": "array", "items": {"type": "number"}}
    from ..units import liquidity_schema, stress_definition_schema
    defn = stress_definition_schema()
    return [
        ToolDef(
            name="value_at_risk",
            title="Value at Risk and Expected Shortfall",
            description=(
                "Market-risk VaR and Expected Shortfall for a book: historical, age-weighted (BRW), filtered historical "
                "(EWMA), Monte Carlo (normal or Student-t from the return covariance) or parametric (delta-normal); full "
                "revaluation or Taylor; optional stressed VaR (the worst 250-day window), Euler component / incremental / "
                "standalone decomposition by trade or group, and liquidity-adjusted VaR (half-spread exit cost plus "
                "sqrt-of-time scaling). History defaults to a 750-day synthetic history with a stress regime. "
                "mode='pnl_series' instead computes VaR/ES from a P&L vector you supply. Example: {\"trades\": "
                "[{\"product\": \"EquityOption\", \"notional\": 1000000, \"tenor_years\": 0.5, \"ticker\": \"SPX\", "
                "\"strike\": 5000, \"is_call\": false}], \"method\": \"historical\", \"horizon_days\": 10}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "mode": {"type": "string", "enum": ["portfolio", "pnl_series"], "default": "portfolio"},
                "method": {"type": "string", "enum": VAR_METHODS, "default": "historical"},
                "confidence": conf, "es_confidence": esc,
                "horizon_days": {"type": "integer", "minimum": 1, "maximum": 250, "default": 1},
                "lookback": {"type": "integer", "minimum": 20, "default": 250, "description": "Scenario window in days."},
                "revaluation": {"type": "string", "enum": ["full", "taylor"], "default": "full"},
                "age_decay": {"type": "number", "exclusiveMinimum": 0, "maximum": 1, "default": 0.98, "description": "age_weighted: decay per day."},
                "ewma_lambda": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1, "description": "filtered_historical (default 0.94), monte_carlo / parametric covariance."},
                "mc_paths": {"type": "integer", "minimum": 100, "maximum": limits.max_mc_paths, "default": 5000},
                "mc_distribution": {"type": "string", "enum": ["normal", "student_t"], "default": "normal"},
                "mc_dof": {"type": "number", "minimum": 2.1, "default": 5.0},
                "seed": {"type": "integer", "default": 7},
                "decomposition": {"type": "boolean", "default": True},
                "group_by": {"type": "object", "additionalProperties": {"type": "string"}, "description": "trade_id -> group (desk, book) for grouped contributions."},
                "include_stressed_var": {"type": "boolean", "default": False},
                "stress_window": {"type": "integer", "minimum": 20, "default": 250},
                "svar_horizon_days": {"type": "integer", "minimum": 1, "default": 10},
                "liquidity": {**liquidity_schema(LIQUIDITY_Q), "title": "Liquidity",
                              "description": "Liquidity-adjusted VaR: spreads_bp (trade id -> bid-ask spread in basis "
                                             "points) and horizon_days."},
                "pnl": {**series, "description": "pnl_series: P&L observations, gains positive."},
                "weights": {**series, "description": "pnl_series: optional scenario weights."},
            }),
            handler=_var,
        ),
        ToolDef(
            name="backtest",
            title="VaR / ES backtest and PLA test",
            description=(
                "Validate a risk model. mode='portfolio' backtests the book's historical VaR and ES over test_days of "
                "(synthetic or supplied) history and runs the FRTB P&L attribution test: exceptions, Kupiec POF, "
                "Christoffersen independence, Basel traffic-light zone and multiplier, Acerbi-Szekely ES Z-tests, PLA "
                "Spearman / KS zone. mode='var_series' / 'es_series' / 'pla' test series you supply (P&L, VaR/ES forecasts as "
                "positive losses, HPL and RTPL). Example: {\"mode\": \"var_series\", \"pnl\": [...250 numbers], "
                "\"var_forecasts\": [...250 numbers]}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "mode": {"type": "string", "enum": ["portfolio", "var_series", "es_series", "pla"], "default": "portfolio"},
                "confidence": conf, "es_confidence": esc,
                "test_days": {"type": "integer", "minimum": 20, "default": 250},
                "lookback": {"type": "integer", "minimum": 20, "default": 250},
                "include_series": {"type": "boolean", "default": False, "description": "portfolio: return the daily HPL, RTPL, VaR and ES series."},
                "pnl": series, "var_forecasts": series, "es_forecasts": series,
                "labels": {"type": "array", "items": {"type": "string"}, "description": "var_series: a label (date) per observation."},
                "hpl": series, "rtpl": series,
            }),
            handler=_backtest,
        ),
        ToolDef(
            name="pnl_explain",
            title="P&L explain",
            description=(
                "Explain a book's P&L between two market states: actual full-revaluation P&L per trade split into theta "
                "(time decay), per-risk-class and per-factor Taylor contributions, and the unexplained remainder. The end "
                "state is end_market_data, or the start market plus end_shocks, and end_valuation_date for the time roll. "
                "Shocks take their unit from the size field: size_bp (basis points), size_pct (percent) or size "
                "(price units). Example: {\"trades\": [...], \"end_shocks\": [{\"factor\": \"EQ.SPX\", \"size_pct\": -5, "
                "\"shock_type\": \"relative\"}], \"end_valuation_date\": \"2026-10-12\"}."),
            input_schema=obj({
                **portfolio_props(limits),
                "end_market_data": {"type": "object", "description": "End-of-period market data (same shape as market_data)."},
                "end_shocks": {"type": "array", "items": shock_schema()},
                "end_valuation_date": {"type": "string", "format": "date"},
            }, ["trades"]),
            handler=_explain,
        ),
        ToolDef(
            name="stress_test",
            title="Stress testing",
            description=(
                "Stress a book. mode='library' revalues it under qlrisk's historical crisis scenarios (" + ", ".join(lib) + ") "
                "or a chosen subset; mode='custom' under your scenarios, each a list of shocks (factor or curve twist / "
                "butterfly / parallel; the size field names its unit: size_bp for absolute rate, spread and dividend "
                "shocks, size_pct for relative and log shocks and absolute vol-point shocks, size for absolute price "
                "and FX spot shocks) or a stylised definition (equity_pct, vol_pct, credit_pct, commodity_pct, "
                "fx_usd_pct, fx_pct relative moves in percent; rates_bp absolute in basis points, or [short, long] "
                "for a 2y-10y twist); "
                "mode='reverse' finds the most plausible market move (minimum Mahalanobis distance) that loses target_loss. "
                "Returns P&L per scenario and per trade, worst first. Example: {\"trades\": [...], \"mode\": \"custom\", "
                "\"custom_scenarios\": [{\"name\": \"rates +100bp\", \"shocks\": [{\"risk_classes\": [\"IR\"], \"shape\": "
                "\"parallel\", \"size_bp\": 100}]}]}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "mode": {"type": "string", "enum": ["library", "custom", "reverse"], "default": "library"},
                "scenarios": {"type": "array", "items": {"type": "string", "enum": lib}},
                "custom_scenarios": {"type": "array", "items": obj({
                    "name": {"type": "string"},
                    "shocks": {"type": "array", "items": shock_schema()},
                    "definition": {**defn, "title": "Stylised scenario",
                                   "description": "Relative moves in percent (equity_pct, vol_pct, credit_pct, commodity_pct, "
                                                  "fx_usd_pct, fx_pct) and an absolute rates move in basis points (rates_bp)."},
                })},
                "target_loss": {"type": "number", "exclusiveMinimum": 0, "description": "reverse: loss to reach, positive."},
                "lookback": {"type": "integer", "minimum": 20, "default": 250},
                "top_n": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            }, ["trades"]),
            handler=_stress,
        ),
    ]
