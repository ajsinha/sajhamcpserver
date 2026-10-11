# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
How the core qlrisk tools present their inputs: essentials first, the rest in one optional ``advanced``
object, human units, a title on every field and a worked example.

The handlers (tools/*.py) keep reading flat arguments in qlrisk's units; this module builds the presented
schema from each handler's schema (``present``) and turns presented arguments back into handler arguments
(``to_handler_args``). One table per tool (LAYOUTS): its essential fields, its renamed fields (a confidence
level in percent, a recovery in percent) and its worked example. Trades inside any tool are in the units of
the per-product tools (rates in percent, maturities as tenors); inputs.build_trades converts them. Calculator
``inputs`` / ``config`` objects (credit_risk, xva, ccr_exposure calculator mode), shocks, stylised stresses and
liquidity spreads are in the same human units too; the handlers convert them with units.py from the table in
generate.py (CALC_INPUTS, CALC_CONFIG, SHOCK_UNITS, STRESS_DEFINITION, LIQUIDITY).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from ..inputs import InvalidInput


@dataclass(frozen=True)
class Unit:
    """A handler argument shown under another name and unit: handler value = shown value x scale."""
    arg: str
    name: str
    title: str
    desc: str
    scale: float = 0.01
    minimum: float = 50.0
    maximum: float = 99.99


def _conf(arg: str, name: str, what: str) -> Unit:
    return Unit(arg, name, f"{what} (%)", f"{what} in percent: 99 means 99% (not 0.99).")


@dataclass(frozen=True)
class Layout:
    essentials: Tuple[str, ...]
    units: Tuple[Unit, ...] = ()
    example: Dict[str, Any] = field(default_factory=dict)


# worked-example trades, in the per-product tools' units
SWAP = {"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10_000_000,
        "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}
BOND = {"product": "CorporateBond", "trade_id": "ACME-5Y", "maturity": "5Y", "face_value": 5_000_000, "coupon_pct": 5,
        "issuer": "ACME", "counterparty_id": "ACME"}
PUT = {"product": "EquityOption", "trade_id": "SPX-P", "maturity": "6M", "notional": 1_000_000, "ticker": "SPX",
       "strike": 5000, "option_type": "put", "counterparty_id": "BANK-B"}

CONF, ES_CONF = _conf("confidence", "confidence_pct", "VaR confidence"), _conf("es_confidence", "es_confidence_pct", "ES confidence")

LAYOUTS: Dict[str, Layout] = {
    "catalog": Layout(("topic", "name", "category"), example={"topic": "products", "category": "fx"}),
    "price_trades": Layout(("trades",), example={"trades": [SWAP, BOND]}),
    "sensitivities": Layout(("trades", "ladder_vertices"), example={"trades": [SWAP], "ladder_vertices": "frtb_girr"}),
    "value_at_risk": Layout(("trades", "method", "confidence_pct", "es_confidence_pct", "horizon_days"), (CONF, ES_CONF),
                            example={"trades": [PUT], "method": "historical", "confidence_pct": 99, "horizon_days": 10}),
    "backtest": Layout(("trades", "mode", "confidence_pct", "test_days"), (CONF, ES_CONF),
                       example={"trades": [SWAP, PUT], "confidence_pct": 99}),
    "pnl_explain": Layout(("trades", "end_shocks", "end_valuation_date"),
                          example={"trades": [PUT], "end_shocks": [{"factor": "EQ.SPX", "size_pct": -5,
                                                                     "shock_type": "relative"}]}),
    "stress_test": Layout(("trades", "mode", "scenarios", "custom_scenarios", "target_loss"),
                          example={"trades": [SWAP, PUT], "mode": "custom", "custom_scenarios": [
                              {"name": "rates +100bp", "shocks": [{"risk_classes": ["IR"], "shape": "parallel",
                                                                   "size_bp": 100}]},
                              {"name": "SPX -20%", "shocks": [{"factor": "EQ.SPX", "shock_type": "relative",
                                                               "size_pct": -20}]},
                              {"name": "risk off", "definition": {"equity_pct": -20, "vol_pct": 50, "credit_pct": 50,
                                                                  "rates_bp": -50}}]}),
    "frtb_sa_capital": Layout(("trades", "mode"),
                              example={"trades": [SWAP, BOND, PUT],
                                       "advanced": {"credit_buckets": {"ACME": 4}, "equity_buckets": {"SPX": 12},
                                                    "ratings": {"ACME": "BBB"}, "vol_underlyings": {"eq_vol": "SPX"}}}),
    "frtb_ima_capital": Layout(("trades", "mode"),
                               (_conf("es_confidence", "es_confidence_pct", "ES confidence"),
                                Unit("drc_confidence", "drc_confidence_pct", "DRC confidence (%)",
                                     "DRC confidence in percent: 99.9 means 99.9%.", maximum=99.999)),
                               example={"trades": [PUT], "mode": "imcc"}),
    "basel25_capital": Layout(("var_series", "svar_series", "exceptions", "trades"),
                              example={"var_series": [1_000_000], "svar_series": [2_000_000], "exceptions": 3}),
    "ccr_exposure": Layout(("trades", "mode", "measure", "inputs"),
                           (_conf("confidence_level", "confidence_pct", "PFE confidence"),),
                           example={"trades": [SWAP], "mode": "trade_profiles"}),
    "saccr": Layout(("trades", "mode", "csa"),
                    example={"trades": [SWAP], "csa": {"BANK-A": {"margined": True, "threshold": 0}}}),
    "initial_margin": Layout(("positions", "method"), (_conf("confidence_level", "confidence_pct", "Confidence"),),
                             example={"method": "simm", "positions": [{"notional": 10_000_000, "product_type": "irs",
                                                                       "remaining_maturity": 5,
                                                                       "delta_sensitivities": {"5y": 4500}}]}),
    "credit_risk": Layout(("measure", "inputs", "config"),
                          example={"measure": "el", "inputs": {"pd_pct": 2, "lgd_pct": 45, "ead": 1_000_000}}),
    "xva": Layout(("measure", "inputs", "counterparty", "time_grid", "expected_exposure", "recovery_pct"),
                  (Unit("recovery", "recovery_pct", "Recovery rate (%)", "sa_cva / ba_cva: counterparty recovery in "
                        "percent: 40 means 40%.", minimum=0.0, maximum=99.0),),
                  example={"measure": "cva", "inputs": {"ee_profile": [400_000, 600_000, 700_000, 650_000, 500_000],
                                                        "time_grid": [1, 2, 3, 4, 5], "credit_spread_bp": 100,
                                                        "recovery_pct": 40}}),
    "simulate_paths": Layout(("process", "initial_value", "drift", "volatility", "maturity", "num_paths"),
                             example={"process": "gbm", "initial_value": 100, "drift": 0.05, "volatility": 0.2,
                                      "maturity": 1, "num_paths": 10000}),
    "risk_report": Layout(("trades", "use_demo_book", "measures", "limits"), (CONF, ES_CONF),
                          example={"use_demo_book": True, "limits": [{"name": "Firm 1d VaR", "metric": "var.1d",
                                                                      "limit": 500_000}]}),
    "check_limits": Layout(("metrics", "limits"),
                           example={"metrics": {"var.1d": 420_000},
                                    "limits": [{"name": "Firm VaR", "metric": "var.1d", "limit": 500_000}]}),
}

_DAYS = "in days"
# titles (and a unit note) for the fields the handlers' schemas leave bare
TITLES: Dict[str, Tuple[str, str]] = {
    "trades": ("Trades", "Each trade is 'product' plus the inputs of its qlrisk_price_<product> tool, flat: rates in "
               "percent, spreads in basis points, maturity as a tenor (5Y) or a date."),
    "market_data": ("Market data", ""), "reporting_currency": ("Reporting currency", ""),
    "history": ("History", ""), "include_cash_flows": ("Include cash flows", ""),
    "horizon_days": ("Horizon (days)", _DAYS), "lookback": ("Lookback (days)", "Scenario window in days."),
    "test_days": ("Test window (days)", _DAYS), "stress_window": ("Stress window (days)", _DAYS),
    "svar_horizon_days": ("Stressed VaR horizon (days)", _DAYS), "current_window": ("Current window (days)", _DAYS),
    "time_horizon": ("Time horizon (years)", "In years."),
    "maturity": ("Horizon (years)", "Simulated horizon in years."),
    "drift": ("Drift (per year, decimal)", "Annual drift as a decimal: 0.05 = 5% a year (gbm, heston, merton_jump)."),
    "volatility": ("Volatility (per year, decimal)", "Annual volatility as a decimal in the process's units: gbm "
                   "0.2 = 20%; rate models an absolute rate volatility (0.01 = 100bp)."),
    "initial_value": ("Initial value", "Starting level: a price (gbm) or a rate as a decimal (ou, cir, vasicek, "
                      "hull_white: 0.04 = 4%)."),
    "num_paths": ("Paths", ""), "num_steps": ("Time steps", ""),
    "rho": ("IMCC weight (0 to 1)", ""), "global_correlation": ("Global correlation (0 to 1)", ""),
    "sector_correlation": ("Sector correlation (0 to 1)", ""), "correlation": ("Correlation (-1 to 1)", ""),
    "age_decay": ("Age decay (0 to 1)", ""), "ewma_lambda": ("EWMA lambda (0 to 1)", ""),
    "multiplier": ("Multiplier", ""), "exceptions": ("Backtest exceptions", "Exceptions in the last 250 days."),
    "var_series": ("VaR series", "Daily 10-day VaR figures (positive losses), oldest first."),
    "svar_series": ("Stressed VaR series", "Daily 10-day stressed VaR figures (positive losses), oldest first."),
    "inputs": ("Calculator inputs", "Probabilities, LGDs, recoveries, rates, haircuts and volatilities in percent "
               "(pd_pct 2 = 2%), spreads in basis points (credit_spread_bp 120 = 1.2%), maturities in years, margin "
               "periods in business days."),
    "config": ("Calculator configuration", "Same units as the inputs (confidence_pct 99.9 = 99.9%)."),
    "target_loss": ("Target loss", "reverse: the loss to reach, positive, in the reporting currency."),
}


def _title(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _decorate(name: str, prop: Dict[str, Any]) -> Dict[str, Any]:
    prop = dict(prop)
    title, note = TITLES.get(name, (None, ""))
    prop.setdefault("title", title or _title(name))
    if note and note not in (prop.get("description") or ""):
        prop["description"] = (prop["description"].rstrip(".") + ". " + note) if prop.get("description") else note
    return prop


def present(tool: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    """The schema a caller sees: units renamed, titles, essentials first, the rest in `advanced`, an example."""
    lay = LAYOUTS.get(tool)
    if lay is None:
        return schema
    props = copy.deepcopy(schema.get("properties") or {})
    required = list(schema.get("required") or [])
    for u in lay.units:
        if u.arg not in props:
            raise ValueError(f"{tool}: no field {u.arg!r} to show as {u.name!r}")
        old = props.pop(u.arg)
        new = {"type": "number", "title": u.title, "description": u.desc, "minimum": u.minimum, "maximum": u.maximum}
        if isinstance(old.get("default"), (int, float)):
            new["default"] = round(old["default"] / u.scale, 6)
        props[u.name] = new
        required = [u.name if r == u.arg else r for r in required]
    props = {k: _decorate(k, v) for k, v in props.items()}
    missing = [r for r in required if r not in lay.essentials]
    if missing:
        raise ValueError(f"{tool}: required fields {missing} must be essentials")
    main = {k: props[k] for k in lay.essentials if k in props}
    rest = {k: v for k, v in props.items() if k not in main}
    if rest:
        main["advanced"] = {"type": "object", "properties": rest, "additionalProperties": False,
                            "title": "Advanced (optional)",
                            "description": "Optional settings: " + ", ".join(rest) + "."}
    out = {k: v for k, v in schema.items() if k not in ("properties", "required")}
    out["properties"] = main
    if required:
        out["required"] = required
    if lay.example:
        out["examples"] = [lay.example]
    return out


def to_handler_args(tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Presented arguments -> the handler's flat arguments in qlrisk's units."""
    lay = LAYOUTS.get(tool)
    if lay is None:
        return args
    flat = {k: v for k, v in args.items() if k != "advanced"}
    adv = args.get("advanced") or {}
    if not isinstance(adv, dict):
        raise InvalidInput("advanced must be an object")
    clash = set(adv) & set(flat)
    if clash:
        raise InvalidInput(f"{sorted(clash)} given both at the top level and in advanced")
    flat.update(adv)
    for u in lay.units:
        if u.name in flat:
            value = flat.pop(u.name)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not (u.minimum <= value <= u.maximum):
                hint = " (it is in percent: 99 means 99%)" if isinstance(value, (int, float)) and 0 < value < 1 else ""
                raise InvalidInput(f"{u.name}: {value!r} is outside {u.minimum} to {u.maximum}{hint}")
            flat[u.arg] = round(value * u.scale, 10)
    return flat


def example(tool: str) -> Optional[Dict[str, Any]]:
    lay = LAYOUTS.get(tool)
    return copy.deepcopy(lay.example) if lay and lay.example else None
