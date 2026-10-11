# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""simulate_paths, risk_report and check_limits: Monte Carlo paths, the unified RiskEngine, limits."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

import numpy as np

from .. import introspect as I
from ..inputs import InvalidInput, _coerce, build_history, build_market_data, build_trades, check_paths
from ..jsonable import rounded, to_jsonable
from . import Ctx, ToolDef, currency_prop, obj, portfolio_props

MAX_POINTS = 60


def _paths(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.mathlib import MathFactory, PathGenerationParams, ProcessType
    proc = args["process"]
    if proc not in I.supported_processes():
        raise InvalidInput(f"process must be one of {I.supported_processes()}")
    params = {k: v for k, v in args.items() if k in I.path_params_schema()["properties"]}
    params["num_paths"] = check_paths(params.get("num_paths", 1000), ctx.limits, "num_paths")
    steps = int(params.get("num_steps", 252))
    if not 1 <= steps <= ctx.limits.max_time_steps:
        raise InvalidInput(f"num_steps must be between 1 and max_time_steps={ctx.limits.max_time_steps}")
    params["num_steps"] = steps
    params.setdefault("seed", 7)
    try:
        p = PathGenerationParams(**params)
    except TypeError as exc:
        raise InvalidInput(f"parameters: {exc}") from None
    gen = MathFactory.get_instance().create_path_generator(implementation="python")
    res = gen.generate_paths(p, ProcessType(proc))
    paths, grid = np.asarray(res.paths), np.asarray(res.time_grid)
    idx = np.unique(np.linspace(0, len(grid) - 1, min(len(grid), MAX_POINTS)).round().astype(int))
    pct = [float(x) for x in args.get("percentiles", [5, 50, 95])]
    if any(not 0 <= x <= 100 for x in pct):
        raise InvalidInput("percentiles must be between 0 and 100")
    term = paths[:, -1]
    k = min(int(args.get("sample_paths", 3)), 10)
    out = {
        "process": proc, "num_paths": int(paths.shape[0]), "num_steps": steps, "dt": float(res.dt),
        "time_grid": grid[idx].tolist(), "mean": paths[:, idx].mean(axis=0).tolist(), "std": paths[:, idx].std(axis=0).tolist(),
        "percentiles": {f"p{x:g}": np.percentile(paths[:, idx], x, axis=0).tolist() for x in pct},
        "terminal": {"mean": float(term.mean()), "std": float(term.std()), "min": float(term.min()), "max": float(term.max()),
                     **{f"p{x:g}": float(np.percentile(term, x)) for x in pct}},
        "sample_paths": paths[:k][:, idx].tolist(),
        "parameters": to_jsonable(p), "metadata": to_jsonable(res.metadata),
    }
    return out, (f"{paths.shape[0]} {proc} paths x {steps} steps: terminal mean {out['terminal']['mean']:.6g}, "
                 f"std {out['terminal']['std']:.6g}")


def _limits(items, what="limits"):
    from qlrisk.reporting import RiskLimit
    return [_coerce(x, RiskLimit, f"{what}[{i}]") for i, x in enumerate(items or [])]


def _checks(checks) -> List[Dict[str, Any]]:
    return [to_jsonable(c) for c in checks]


def _report(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.engine import ALL_MEASURES, DEFAULT_MEASURES, RiskEngine
    from qlrisk.regulatory.saccr_netting import CSATerms
    from qlrisk.reporting import Hierarchy
    measures = args.get("measures") or list(DEFAULT_MEASURES)
    bad = [m for m in measures if m.upper() not in ALL_MEASURES]
    if bad:
        raise InvalidInput(f"measures: unknown {bad}; choose from {list(ALL_MEASURES)}")
    tree, frtb = None, args.get("frtb")
    if args.get("use_demo_book"):
        from qlrisk.demos import demo_book
        trades, md, hist, tree, frtb_maps = demo_book()
        frtb = frtb or frtb_maps
        if args.get("market_data") or args.get("history"):
            ctx.warnings.append("use_demo_book: the demo book brings its own market (qlrisk's sample valued today) "
                                "and history; market_data and history were ignored")
        if args.get("trades"):
            raise InvalidInput("give trades or use_demo_book, not both")
    else:
        md = build_market_data(args.get("market_data"))
        trades = build_trades(args.get("trades") or [], md, ctx.limits, ctx.warnings)
        hist = build_history(args.get("history"), md, ctx.limits)
    if args.get("hierarchy"):
        h = args["hierarchy"]
        if not h.get("paths"):
            raise InvalidInput("hierarchy needs paths: {trade_id: [entity, desk, book]}")
        missing = [t.trade_id for t in trades if t.trade_id not in h["paths"]]
        if missing:
            raise InvalidInput(f"hierarchy.paths has no path for {missing}")
        tree = Hierarchy(h["paths"], tuple(h.get("levels") or ("entity", "desk", "book")))
    csa = {ns: _coerce(v, CSATerms, f"csa.{ns}") for ns, v in (args.get("csa") or {}).items()} or None
    ccy = args.get("reporting_currency", "USD")
    eng = RiskEngine(reporting_currency=ccy, confidence=float(args.get("confidence", 0.99)),
                     es_confidence=float(args.get("es_confidence", 0.975)), lookback=int(args.get("lookback", 250)),
                     horizon_days=int(args.get("horizon_days", 10)), stress_window=int(args.get("stress_window", 250)))
    if eng.lookback >= len(hist) or eng.stress_window >= len(hist):
        raise InvalidInput(f"lookback / stress_window need a history longer than {len(hist)} days")
    rep = eng.run(trades, md, hist, measures=measures, hierarchy=tree, limits=_limits(args.get("limits")) or None,
                  frtb=frtb, csa=csa)
    out = rep.to_dict()
    out["measures"] = [m.upper() for m in measures]
    out["trades"] = [t.trade_id for t in trades]
    if "limits" in rep.results:
        out["limits"] = _checks(rep.results["limits"])
    if "stress" in rep.results:
        out["stress"] = to_jsonable(rep.results["stress"])
    if "netting_sets" in rep.results:
        out["netting_sets"] = {k: {"ead": v.ead, "replacement_cost": v.replacement_cost, "addon": v.addon}
                               for k, v in rep.results["netting_sets"].items()}
    met = rep.metrics
    head = [f"{k} {rounded(met[k])}" for k in ("pv.total", "var.1d", "es.1d", f"svar.{eng.horizon_days}d", "frtb_sa.total",
                                               "exposure.saccr_ead_netted") if k in met]
    breaches = [c for c in rep.results.get("limits", []) if c.status is not None and c.status.value == "breach"]
    return out, f"Risk report {rep.as_of} in {ccy}: " + ", ".join(head) + (f"; {len(breaches)} limit breach(es)" if breaches else "")


def _check_limits(args: Dict[str, Any], ctx: Ctx):
    from qlrisk.reporting import RiskReport, breaches, check_limits
    metrics = args.get("metrics") or {}
    by_node = args.get("by_node") or {}
    if not metrics and not by_node:
        raise InvalidInput("give metrics ({'var.1d': 420000, ...}) and/or by_node ({'Rates': {'var.1d': ...}})")
    lims = _limits(args.get("limits"))
    if not lims:
        raise InvalidInput("limits: send at least one limit {name, metric, limit}")
    rep = RiskReport(date.today(), args.get("currency"), {k: float(v) for k, v in metrics.items()},
                     {n: {k: float(v) for k, v in vals.items()} for n, vals in by_node.items()})
    checks = check_limits(rep, lims)
    br = breaches(checks)
    out = {"checks": _checks(checks), "breaches": [c.name for c in br]}
    counts: Dict[str, int] = {}
    for c in checks:
        s = c.status.value if c.status else "no_value"
        counts[s] = counts.get(s, 0) + 1
    out["counts"] = counts
    return out, f"{len(checks)} limit(s) checked: " + ", ".join(f"{v} {k}" for k, v in counts.items())


def tools(limits) -> List[ToolDef]:
    from qlrisk.reporting import RiskLimit
    from qlrisk.regulatory.saccr_netting import CSATerms
    pp = dict(I.path_params_schema()["properties"])
    pp["num_paths"] = {**pp.get("num_paths", {}), "type": "integer", "minimum": 1, "maximum": limits.max_mc_paths, "default": 1000}
    pp["num_steps"] = {**pp.get("num_steps", {}), "type": "integer", "minimum": 1, "maximum": limits.max_time_steps, "default": 252}
    pp["seed"] = {"type": "integer", "default": 7}
    lim_schema = I.dataclass_schema(RiskLimit)
    measures = I.report_measures()
    return [
        ToolDef(
            name="simulate_paths",
            title="Monte Carlo path generation",
            description=(
                "Simulate stochastic-process paths with qlrisk's Monte Carlo library: " + ", ".join(I.supported_processes()) +
                ". Rate models (ou, cir, vasicek, hull_white) use initial_value as the starting rate and "
                "mean_reversion_speed / long_term_mean; heston adds vol_of_vol, correlation, initial_variance; merton_jump "
                "adds jump_intensity, jump_mean, jump_std. Returns summary statistics on up to 60 time points, the terminal "
                "distribution and a few sample paths (not the full path matrix). Example: {\"process\": \"gbm\", "
                "\"initial_value\": 100, \"drift\": 0.05, \"volatility\": 0.2, \"maturity\": 1, \"num_steps\": 252, "
                f"\"num_paths\": 10000}}. Bounds: {limits.max_mc_paths} paths, {limits.max_time_steps} steps."),
            input_schema=obj({
                "process": {"type": "string", "enum": I.supported_processes()},
                **{k: v for k, v in pp.items()},
                "percentiles": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 100}, "default": [5, 50, 95]},
                "sample_paths": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
            }, ["process", "initial_value"]),
            handler=_paths,
        ),
        ToolDef(
            name="risk_report",
            title="Unified risk report",
            description=(
                "Every risk in one call with qlrisk's RiskEngine: PV, sensitivities (DV01/CS01/delta/vega), historical VaR "
                "and ES, parametric VaR, stressed VaR, the stress library, backtest, FRTB SA capital and counterparty "
                "exposure (peak PFE and SA-CCR EAD netted per netting set), rolled up a reporting hierarchy (VaR and ES "
                "are non-additive, recomputed per node), with optional limit checks. measures: " + ", ".join(measures["all"]) +
                " (default " + ", ".join(measures["default"]) + "). use_demo_book=true runs qlrisk's six-trade demo book "
                "(swap, bond, CDS, FX option, equity option, commodity forward) with its history, hierarchy and FRTB maps. "
                "Example: {\"use_demo_book\": true, \"limits\": [{\"name\": \"Firm 1d VaR\", \"metric\": \"var.1d\", "
                "\"limit\": 500000}]}."),
            input_schema=obj({
                **portfolio_props(limits, history=True),
                "use_demo_book": {"type": "boolean", "default": False},
                "measures": {"type": "array", "items": {"type": "string", "enum": measures["all"]}},
                "confidence": {"type": "number", "default": 0.99},
                "es_confidence": {"type": "number", "default": 0.975},
                "lookback": {"type": "integer", "default": 250},
                "horizon_days": {"type": "integer", "default": 10},
                "stress_window": {"type": "integer", "default": 250},
                "hierarchy": obj({"levels": {"type": "array", "items": {"type": "string"}, "default": ["entity", "desk", "book"]},
                                  "paths": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}},
                                            "description": "trade_id -> path, e.g. ['Bank', 'Rates', 'Swaps']."}}, ["paths"],
                                 description="Reporting tree; default one node per counterparty."),
                "limits": {"type": "array", "items": lim_schema, "description": "Limits on report metrics, e.g. var.1d, es.1d, pv.total, dv01.IR."},
                "frtb": {"type": "object", "description": "FRTB SA maps (credit_buckets, equity_buckets, ratings, vol_underlyings ...), as in frtb_sa_capital."},
                "csa": {"type": "object", "additionalProperties": I.dataclass_schema(CSATerms)},
            }),
            handler=_report,
        ),
        ToolDef(
            name="check_limits",
            title="Limit monitoring",
            description=(
                "Check risk numbers against limits with qlrisk's limit monitor: utilisation and a status per limit "
                "(" + ", ".join(I.enum_values("LimitStatus")) + "; amber and red thresholds as fractions of the limit), "
                "headline metrics under node 'ALL' or per hierarchy node. Use it for figures you already have; qlrisk_risk_report "
                "checks limits on the figures it computes. Example: {\"metrics\": {\"var.1d\": 420000}, \"limits\": "
                "[{\"name\": \"Firm VaR\", \"metric\": \"var.1d\", \"limit\": 500000}]}."),
            input_schema=obj({
                "metrics": {"type": "object", "additionalProperties": {"type": "number"}},
                "by_node": {"type": "object", "additionalProperties": {"type": "object", "additionalProperties": {"type": "number"}}},
                "limits": {"type": "array", "items": lim_schema, "minItems": 1},
                "currency": currency_prop(),
            }, ["limits"]),
            handler=_check_limits,
        ),
    ]
