# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""frtb_sa_capital, frtb_ima_capital and basel25_capital: market-risk regulatory capital."""

from __future__ import annotations

from typing import Any, Dict, List

from .. import introspect as I
from ..inputs import InvalidInput, _coerce, build_history, build_market_data, build_trades, parse_date
from ..jsonable import rounded, to_jsonable
from . import Ctx, ToolDef, obj, portfolio_props


def _dc_list(items, cls, what):
    if not items:
        raise InvalidInput(f"{what}: send at least one entry")
    return [_coerce(x, cls, f"{what}[{i}]") for i, x in enumerate(items)]


def _sbm(r) -> Dict[str, Any]:
    return {"total": r.total, "scenario": r.scenario, "by_scenario": to_jsonable(r.by_scenario),
            "by_component": to_jsonable(r.by_component), "by_bucket": to_jsonable(r.by_bucket),
            "skipped_factors": list(r.skipped_factors)}


def _frtb_sa(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.regulatory.frtb_sa import DRCPosition, FRTBSensitivity, drc_charge, frtb_sa_capital, sbm_capital
    mode = args.get("mode", "portfolio")
    if mode == "sbm_from_sensitivities":
        fs = _dc_list(args.get("frtb_sensitivities"), FRTBSensitivity, "frtb_sensitivities")
        r = sbm_capital(fs, csr_sector_gamma=args.get("csr_sector_gamma"))
        return {"mode": mode, "sbm": _sbm(r)}, f"SBM capital {rounded(r.total)} (binding correlation scenario {r.scenario})"
    if mode == "drc_from_positions":
        ps = _dc_list(args.get("drc_positions"), DRCPosition, "drc_positions")
        r = drc_charge(ps)
        return {"mode": mode, "drc": to_jsonable(r)}, f"FRTB SA DRC {rounded(r.total)}"
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"), None, ctx.warnings)
    trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
    kw = {k: args[k] for k in ("curve_currency", "credit_buckets", "equity_buckets", "commodity_buckets",
                               "vol_underlyings", "ratings", "seniority", "exotic", "other_residual",
                               "csr_sector_gamma", "include_curvature") if k in args}
    r = frtb_sa_capital(trades, md, ccy, **kw)
    out = {"mode": mode, "reporting_currency": ccy, "total": r.total, "summary": to_jsonable(r.summary()),
           "sbm": _sbm(r.sbm), "drc": to_jsonable(r.drc), "rrao": to_jsonable(r.rrao)}
    s = r.summary()
    return out, (f"FRTB SA capital {rounded(r.total)} {ccy}: SBM {rounded(s.get('SBM'))}, DRC {rounded(s.get('DRC'))}, "
                 f"RRAO {rounded(s.get('RRAO'))}" + (f"; unmapped factors {r.sbm.skipped_factors}" if r.sbm.skipped_factors else ""))


def _lh_map(raw, what):
    from qlrisk.riskfactors import as_key
    try:
        return {as_key(k): int(v) for k, v in (raw or {}).items()} or None
    except Exception as exc:
        raise InvalidInput(f"{what}: {exc}") from None


def _keys(raw, what):
    from qlrisk.riskfactors import as_key
    try:
        return [as_key(k) for k in raw or []]
    except Exception as exc:
        raise InvalidInput(f"{what}: {exc}") from None


def _ima(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.regulatory import default_liquidity_horizon, ima_capital, ima_drc, imcc, liquidity_adjusted_es, rfet, ses
    from qlrisk.regulatory.frtb_sa import DRCPosition, drc_positions_from_trades
    mode = args.get("mode", "full")
    if mode == "capital":
        for k in ("imcc", "ses"):
            if k not in args:
                raise InvalidInput(f"capital mode needs imcc and ses (and optionally drc, multiplier, imcc_avg60, ses_avg60)")
        cap = ima_capital(float(args["imcc"]), float(args["ses"]), float(args.get("drc", 0.0)),
                          float(args.get("multiplier", 1.5)), args.get("imcc_avg60"), args.get("ses_avg60"))
        return {"mode": mode, "capital": cap}, f"IMA capital {rounded(cap)}"
    if mode == "rfet":
        as_of = parse_date(args.get("as_of") or __import__("datetime").date.today().isoformat(), "as_of")
        obs = args.get("observations")
        if not obs:
            raise InvalidInput("rfet needs observations: {factor: [dates of real prices]}")
        res = {k: bool(rfet([parse_date(d, f"observations.{k}") for d in v], as_of)) for k, v in obs.items()}
        failing = [k for k, ok in res.items() if not ok]
        return {"mode": mode, "as_of": as_of.isoformat(), "modellable": res, "non_modellable": failing}, \
            f"RFET: {len(res) - len(failing)} of {len(res)} factor(s) modellable" + (f"; NMRF {failing}" if failing else "")
    if mode == "ima_drc":
        ps = _dc_list(args.get("drc_positions"), DRCPosition, "drc_positions")
        n = int(args.get("n_sims", 50_000))
        if n > ctx.limits.max_drc_simulations:
            raise InvalidInput(f"n_sims={n} exceeds max_drc_simulations={ctx.limits.max_drc_simulations}")
        r = ima_drc(ps, n_sims=n, global_correlation=float(args.get("global_correlation", 0.15)),
                    sector_correlation=float(args.get("sector_correlation", 0.10)), sectors=args.get("sectors"),
                    confidence=float(args.get("drc_confidence", 0.999)), seed=args.get("seed", 0))
        return {"mode": mode, "drc": to_jsonable(r)}, f"IMA DRC {rounded(r.get('drc'))} ({n} simulations)"

    from qlrisk.engine import MarketRiskEngine
    ccy = args.get("reporting_currency", "USD")
    md = build_market_data(args.get("market_data"), None, ctx.warnings)
    if mode == "liquidity_horizons":
        from qlrisk.riskfactors import enumerate_risk_factors
        lh = {str(k): default_liquidity_horizon(k, ccy, args.get("small_caps", ()), args.get("high_yield", ()))
              for k in enumerate_risk_factors(md)}
        return {"mode": mode, "liquidity_horizons": lh}, f"MAR33.12 liquidity horizons for {len(lh)} factors"
    trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
    hist = build_history(args.get("history"), md, ctx.limits)
    eng = MarketRiskEngine(reporting_currency=ccy)
    lh = _lh_map(args.get("liquidity_horizons"), "liquidity_horizons")
    if mode == "lh_es":
        from qlrisk.scenarios import historical_scenarios
        ten = historical_scenarios(hist, horizon=10).restrict_to(md)
        full = {k: default_liquidity_horizon(k, ccy) for k in ten.factors}
        full.update(lh or {})
        sens = eng.sensitivities(trades, md)
        reval = args.get("revaluation", "taylor")
        pnl_fn = lambda s: eng.scenario_pnl(trades, md, s, reval, sensitivities=sens).portfolio  # noqa: E731
        r = liquidity_adjusted_es(pnl_fn, ten, full, float(args.get("es_confidence", 0.975)))
        return {"mode": mode, "reporting_currency": ccy, "es": r["es"], "components": to_jsonable(r["components"])}, \
            f"Liquidity-adjusted ES {rounded(r['es'])} {ccy}"
    cw, sw = int(args.get("current_window", 250)), int(args.get("stress_window", 250))
    if max(cw, sw) >= len(hist):
        raise InvalidInput(f"current_window / stress_window need a history longer than {len(hist)} days")
    ic = imcc(eng, trades, md, hist, reduced_set=_keys(args.get("reduced_set"), "reduced_set") or None, lh=lh,
              current_window=cw, stress_window=sw, rho=float(args.get("rho", 0.5)), method=args.get("revaluation", "taylor"))
    out: Dict[str, Any] = {"mode": mode, "reporting_currency": ccy, "imcc": to_jsonable(ic)}
    if mode == "imcc":
        return out, f"IMCC {rounded(ic.imcc)} {ccy} (stress window {ic.stress_window[0]} to {ic.stress_window[1]}, ratio {ic.ratio:.2f})"
    if mode != "full":
        raise InvalidInput("mode must be full, imcc, lh_es, liquidity_horizons, rfet, ima_drc or capital")
    nmrf = _keys(args.get("nmrf"), "nmrf")
    ses_val = 0.0
    if nmrf:
        s = ses(eng, trades, md, hist, nmrf, ic.stress_window, lh=lh, idiosyncratic=_keys(args.get("idiosyncratic"), "idiosyncratic"))
        out["ses"] = to_jsonable(s)
        ses_val = float(s["ses"])
    drc_val = 0.0
    if args.get("ratings"):
        positions = drc_positions_from_trades(trades, md, args["ratings"], args.get("seniority"))
        if positions:
            n = int(args.get("n_sims", 50_000))
            if n > ctx.limits.max_drc_simulations:
                raise InvalidInput(f"n_sims={n} exceeds max_drc_simulations={ctx.limits.max_drc_simulations}")
            d = ima_drc(positions, n_sims=n, seed=args.get("seed", 0))
            out["drc"] = to_jsonable(d)
            drc_val = float(d["drc"])
    out["capital"] = ima_capital(ic.imcc, ses_val, drc_val, float(args.get("multiplier", 1.5)))
    return out, f"IMA capital {rounded(out['capital'])} {ccy}: IMCC {rounded(ic.imcc)}, SES {rounded(ses_val)}, DRC {rounded(drc_val)}"


def _basel25(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.regulatory import basel25_capital
    if args.get("trades"):
        from qlrisk.engine import MarketRiskEngine
        from qlrisk.scenarios import historical_scenarios
        ccy = args.get("reporting_currency", "USD")
        md = build_market_data(args.get("market_data"), None, ctx.warnings)
        trades = build_trades(args["trades"], md, ctx.limits, ctx.warnings)
        hist = build_history(args.get("history"), md, ctx.limits)
        if len(hist) < 520:
            raise InvalidInput("basel25 on a book needs a history of at least 520 days (VaR, SVaR and a 250-day backtest)")
        eng = MarketRiskEngine(reporting_currency=ccy)
        var10 = eng.var(trades, md, historical_scenarios(hist, lookback=250, horizon=10, sqrt_scaling=True)).value
        svar10 = eng.stressed_var(trades, md, hist, horizon_days=10).value
        bt = eng.backtest(trades, md, hist, test_days=250)
        exc = bt["var"].exceptions
        r = basel25_capital([var10], [svar10], exceptions=exc)
        out = {"mode": "portfolio", "reporting_currency": ccy, "var_10d": var10, "svar_10d": svar10, "exceptions": exc,
               "result": to_jsonable(r),
               "note": "One VaR and SVaR observation stands in for the 60-day averages."}
        return out, f"Basel 2.5 capital {rounded(r.get('capital'))} {ccy} (VaR10 {rounded(var10)}, SVaR10 {rounded(svar10)}, {exc} exceptions)"
    v, s = args.get("var_series"), args.get("svar_series")
    if not v or not s:
        raise InvalidInput("give var_series and svar_series (the last 60 daily 10-day VaR and SVaR figures), or trades")
    r = basel25_capital(v, s, exceptions=int(args.get("exceptions", 0)))
    return {"mode": "series", "result": to_jsonable(r)}, f"Basel 2.5 capital {rounded(r.get('capital'))}"


def tools(limits) -> List[ToolDef]:
    from qlrisk.regulatory.frtb_sa import DRCPosition, FRTBSensitivity
    imap = {"type": "object", "additionalProperties": {"type": "integer"}}
    smap = {"type": "object", "additionalProperties": {"type": "string"}}
    drc_items = {"type": "array", "items": I.dataclass_schema(DRCPosition)}
    return [
        ToolDef(
            name="frtb_sa_capital",
            title="FRTB Standardised Approach capital",
            description=(
                "FRTB SA market-risk capital (MAR21-23) for a book: sensitivities-based method (GIRR, CSR, equity, "
                "commodity, FX delta, vega and curvature under the low / medium / high correlation scenarios), default risk "
                "charge (non-securitisation) and the residual risk add-on, with breakdowns by component and bucket. Map "
                "names to buckets (credit_buckets {'ACME': 4}, equity_buckets {'SPX': 12}), ratings for DRC ({'ACME': 'BBB'}) "
                "and vol surfaces to underlyings ({'eq_vol': 'SPX'}); unmapped factors are reported. mode='sbm_from_sensitivities' "
                "aggregates FRTB sensitivities you supply; mode='drc_from_positions' charges DRC on positions you supply."),
            input_schema=obj({
                **portfolio_props(limits),
                "mode": {"type": "string", "enum": ["portfolio", "sbm_from_sensitivities", "drc_from_positions"], "default": "portfolio"},
                "curve_currency": {**smap, "description": "Curve name -> currency (e.g. {'SOFR': 'USD'})."},
                "credit_buckets": {**imap, "description": "Issuer / reference -> CSR bucket 1-18."},
                "equity_buckets": {**imap, "description": "Ticker -> equity bucket 1-13."},
                "commodity_buckets": {**imap, "description": "Commodity -> bucket 1-11."},
                "vol_underlyings": {**smap, "description": "Vol surface -> underlying name."},
                "ratings": {**smap, "description": "Obligor -> rating (AAA ... CCC) for the DRC."},
                "seniority": {**smap, "description": "Obligor -> SENIOR / NON_SENIOR / EQUITY / COVERED."},
                "exotic": {"type": "array", "items": {"type": "string"}, "description": "Trade ids with exotic underlyings (RRAO 1%)."},
                "other_residual": {"type": "array", "items": {"type": "string"}, "description": "Trade ids with other residual risk (RRAO 0.1%)."},
                "csr_sector_gamma": {"type": "number", "description": "Flat CSR cross-bucket correlation override."},
                "include_curvature": {"type": "boolean", "default": True},
                "frtb_sensitivities": {"type": "array", "items": I.dataclass_schema(FRTBSensitivity)},
                "drc_positions": drc_items,
            }),
            handler=_frtb_sa,
        ),
        ToolDef(
            name="frtb_ima_capital",
            title="FRTB Internal Models Approach capital",
            description=(
                "FRTB IMA capital (MAR31/33). mode='full' runs the book end to end: liquidity-horizon-adjusted, "
                "stress-calibrated ES and IMCC, stressed ES for non-modellable factors (nmrf), the IMA default risk charge "
                "(two-factor Gaussian copula, from ratings) and capital = max(IMCC + SES, m x avg60) + DRC. Other modes: "
                "'imcc', 'lh_es' (liquidity-adjusted ES only), 'liquidity_horizons' (MAR33.12 horizon per factor), 'rfet' "
                "(risk-factor eligibility test on real-price observation dates), 'ima_drc' (on positions you supply) and "
                "'capital' (from IMCC, SES and DRC numbers). Example: {\"mode\": \"rfet\", \"as_of\": \"2026-10-09\", "
                "\"observations\": {\"CR.GLOBEX.5Y\": [\"2026-09-30\", \"2026-08-29\"]}}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "mode": {"type": "string", "enum": ["full", "imcc", "lh_es", "liquidity_horizons", "rfet", "ima_drc", "capital"], "default": "full"},
                "current_window": {"type": "integer", "minimum": 20, "default": 250},
                "stress_window": {"type": "integer", "minimum": 20, "default": 250},
                "rho": {"type": "number", "default": 0.5, "description": "IMCC weight of the unconstrained ES."},
                "revaluation": {"type": "string", "enum": ["taylor", "full"], "default": "taylor"},
                "reduced_set": {"type": "array", "items": {"type": "string"}, "description": "Reduced factor set for stress calibration."},
                "liquidity_horizons": {**imap, "description": "Factor key -> liquidity horizon (10, 20, 40, 60, 120) overrides."},
                "nmrf": {"type": "array", "items": {"type": "string"}, "description": "Non-modellable factor keys for SES."},
                "idiosyncratic": {"type": "array", "items": {"type": "string"}},
                "ratings": {**smap, "description": "full: obligor -> rating, enables the IMA DRC."},
                "seniority": smap,
                "multiplier": {"type": "number", "minimum": 1.5, "default": 1.5},
                "es_confidence": {"type": "number", "default": 0.975},
                "small_caps": {"type": "array", "items": {"type": "string"}},
                "high_yield": {"type": "array", "items": {"type": "string"}},
                "as_of": {"type": "string", "format": "date"},
                "observations": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string", "format": "date"}}},
                "drc_positions": drc_items,
                "n_sims": {"type": "integer", "minimum": 1000, "maximum": limits.max_drc_simulations, "default": 50000},
                "global_correlation": {"type": "number", "default": 0.15},
                "sector_correlation": {"type": "number", "default": 0.10},
                "sectors": smap,
                "drc_confidence": {"type": "number", "default": 0.999},
                "seed": {"type": "integer", "default": 0},
                "imcc": {"type": "number"}, "ses": {"type": "number"}, "drc": {"type": "number"},
                "imcc_avg60": {"type": "number"}, "ses_avg60": {"type": "number"},
            }),
            handler=_ima,
        ),
        ToolDef(
            name="basel25_capital",
            title="Basel 2.5 market-risk capital",
            description=(
                "Basel 2.5 capital = max(VaR, m x avg60 VaR) + max(SVaR, m x avg60 SVaR), m = 3 + the backtesting plus "
                "factor. Give var_series and svar_series (the last 60 daily 10-day figures) and the backtest exceptions, or "
                "give trades to compute 10-day VaR, SVaR and the exception count from a history. Example: "
                "{\"var_series\": [1000000], \"svar_series\": [2000000], \"exceptions\": 3}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "var_series": {"type": "array", "items": {"type": "number"}},
                "svar_series": {"type": "array", "items": {"type": "number"}},
                "exceptions": {"type": "integer", "minimum": 0, "default": 0},
            }),
            handler=_basel25,
        ),
    ]
