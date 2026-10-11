# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Every qlrisk tool (config/tools/qlrisk), and every mode of each, against the real qlrisk wheel.

The tools are the SAJHA tool classes built from their shipped configs and called through
execute_with_tracking (validation, policy, metrics), as /mcp and the REST API call them."""

import json
import math
from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("qlrisk", reason="qlrisk is not installed (pip install its wheel; see requirements-qlrisk.txt)")

CONFIGS = Path(__file__).resolve().parents[2] / "config" / "tools" / "qlrisk"
NAMES = ["catalog", "price_trades", "sensitivities", "value_at_risk", "backtest", "pnl_explain",
         "stress_test", "frtb_sa_capital", "frtb_ima_capital", "basel25_capital", "ccr_exposure", "saccr",
         "initial_margin", "credit_risk", "xva", "simulate_paths", "risk_report", "check_limits"]


def _build(config):
    import importlib
    module, cls = config["implementation"].rsplit(".", 1)
    return getattr(importlib.import_module(module), cls)(config)


PRODUCT_IMPL = "sajha.tools.impl.qlrisk.qlrisk_tools.QlriskPriceProductTool"


def _configs(products: bool):
    out = []
    for f in sorted(CONFIGS.glob("*.json")):
        cfg = json.loads(f.read_text())
        if (cfg["implementation"] == PRODUCT_IMPL) == products:
            out.append(cfg)
    return out


@pytest.fixture(scope="session")
def tools():
    """The core tools (not the generated per-product pricing tools)."""
    return {cfg["name"]: _build(cfg) for cfg in _configs(products=False)}


@pytest.fixture(scope="session")
def product_tools():
    return {cfg["name"]: (_build(cfg), cfg) for cfg in _configs(products=True)}


@pytest.fixture(scope="session")
def call(tools):
    """call("price_trades", args) runs qlrisk_price_trades; ok=False returns the error message."""
    from sajha.tools.base_mcp_tool import ToolArgumentError

    def _call(name, args, ok=True):
        tool = tools["qlrisk_" + name]
        main = tool.input_schema["properties"]
        args = dict(args)
        adv = {k: args.pop(k) for k in list(args) if k not in main}
        if adv:
            args["advanced"] = {**args.get("advanced", {}), **adv}
        try:
            res = tool.execute_with_tracking(args)
        except (ToolArgumentError, RuntimeError) as exc:
            assert not ok, str(exc)
            return str(exc)
        assert ok, f"expected an error, got {str(res)[:300]}"
        assert isinstance(res, dict)
        return res
    return _call


SWAP = {"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10_000_000,
        "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}
BOND = {"product": "CorporateBond", "trade_id": "ACME-5Y", "maturity": "5Y", "face_value": 5_000_000, "coupon_pct": 5,
        "issuer": "ACME", "counterparty_id": "ACME"}
CDS = {"product": "CreditDefaultSwap", "trade_id": "GLX-CDS", "maturity": "5Y", "notional": 5_000_000,
       "reference": "GLOBEX", "coupon_bp": 100, "counterparty_id": "BANK-B"}
EQO = {"product": "EquityOption", "trade_id": "SPX-P", "maturity": "6M", "notional": 1_000_000, "ticker": "SPX",
       "strike": 5000, "option_type": "put", "counterparty_id": "BANK-B"}
FXO = {"product": "FXOption", "trade_id": "EURUSD-C", "maturity": "1Y", "notional": 2_000_000, "pair": "EURUSD",
       "strike": 1.10, "currency": "EUR", "counterparty_id": "BANK-A"}
BOOK = [SWAP, BOND, CDS, EQO, FXO]
SHORT_HISTORY = {"num_days": 400, "stress_start": 100, "stress_days": 40}
TG = [0.5, 1, 2, 3, 4, 5]
EE = [2e6, 3e6, 3.5e6, 3e6, 2e6, 1e6]


def finite(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


# ── the tools as SAJHA tools ────────────────────────────────────────

def test_configs_names_annotations_and_schemas(tools):
    assert sorted(tools) == sorted("qlrisk_" + n for n in NAMES)
    for name, t in tools.items():
        cfg = json.loads((CONFIGS / f"{name}.json").read_text())
        assert cfg["requires"] == ["qlrisk"] and "__" not in name and "inputSchema" not in cfg
        m = t.to_mcp_format()
        a = m["annotations"]
        assert a["readOnlyHint"] is True and a["idempotentHint"] is True
        assert a["destructiveHint"] is False and a["openWorldHint"] is False
        assert m["inputSchema"]["type"] == "object" and len(m["description"]) > 80
        assert m["outputSchema"] == {"type": "object"} and m["title"]
        json.dumps(m["inputSchema"])


def test_enums_come_from_qlrisk(tools):
    from qlrisk.products.base import Currency
    from qlrisk.scenarios import STRESS_LIBRARY
    import qlrisk.products.python as P
    trade = tools["qlrisk_price_trades"].input_schema["properties"]["trades"]["items"]["properties"]
    from sajha.tools.impl.qlrisk.tools.products import trade_item_schema
    assert trade_item_schema("InterestRateSwap")["properties"]["currency"]["enum"] == [c.value for c in Currency]
    assert "InterestRateSwap" in trade["product"]["enum"] and len(trade["product"]["enum"]) >= 80
    assert set(trade["product"]["enum"]) <= set(P.__all__)
    stress = tools["qlrisk_stress_test"].input_schema["properties"]["scenarios"]["items"]["enum"]
    assert stress == list(STRESS_LIBRARY)


def test_mcp_result_is_structured_content_plus_summary_then_json(tools):
    t = tools["qlrisk_price_trades"]
    res = t.format_mcp_result(t.execute_with_tracking({"trades": [SWAP]}))
    summary, body = res["content"][0]["text"].split("\n", 1)
    assert "total NPV" in summary and json.loads(body)["trades"][0]["trade_id"] == "IRS-5Y"
    assert res["structuredContent"]["trades"][0]["trade_id"] == "IRS-5Y"
    assert "structuredContent" not in t.format_mcp_result({"a": 1}, advertise_output_schema=False)


def test_invalid_input_is_a_clear_error(call):
    assert "not one of" in call("price_trades", {"trades": [{"product": "Nope"}]}, ok=False)
    assert "'maturity' is a required property" in call("price_trades", {"trades": [{"product": "InterestRateSwap", "notional": 1e6}]}, ok=False)
    old = call("price_trades", {"trades": [{"product": "InterestRateSwap", "tenor_years": 5, "fixed_rate": 0.044}]}, ok=False)
    assert "trades[0] (InterestRateSwap)" in old and "fixed_rate_pct" in old and "percent" in old   # the old units are named
    assert "confidence_pct" in call("value_at_risk", {"trades": [SWAP], "confidence_pct": 0.99}, ok=False)
    assert "additional" in call("catalog", {"topic": "products", "colour": 1}, ok=False).lower()
    assert "maximum of 20000" in call("simulate_paths", {"process": "gbm", "initial_value": 100, "num_paths": 10**6}, ok=False)
    assert "is not a date" in call("price_trades", {"trades": [SWAP], "market_data": {"valuation_date": "soon"}}, ok=False)


def test_bounds_are_enforced(call, monkeypatch):
    from sajha.tools.impl.qlrisk.options import Limits
    assert "maximum of 2500" in call("value_at_risk", {"trades": [SWAP], "history": {"num_days": 9999}}, ok=False)
    assert "max_mc_paths" in call("ccr_exposure", {"mode": "calculator", "measure": "pfe", "inputs": {
        "current_mtm": 1, "notional": 1, "remaining_maturity": 1, "volatility": 0.1, "num_simulations": 10**7}}, ok=False)
    monkeypatch.setenv("SAJHA_QLRISK_MAX_MC_PATHS", "500")
    lim = Limits.from_config({"max_trades": 3})
    assert lim.max_mc_paths == 500 and lim.max_trades == 3
    with pytest.raises(ValueError, match="unknown qlrisk bound"):
        Limits.from_config({"max_paths": 1})


def test_a_tool_config_bounds_object_lowers_one_tool(tools):
    cfg = json.loads((CONFIGS / "qlrisk_price_trades.json").read_text())
    small = _build(dict(cfg, bounds={"max_trades": 1}))
    assert small.input_schema["properties"]["trades"]["maxItems"] == 1
    from sajha.tools.base_mcp_tool import ToolArgumentError
    with pytest.raises(ToolArgumentError):
        small.execute_with_tracking({"trades": [SWAP, SWAP]})


# ── catalog ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("topic", ["products", "calculators", "stress_scenarios", "report_measures", "processes",
                                   "market_data", "enumerations", "version"])
def test_catalog_topics(call, topic):
    out = call("catalog", {"topic": topic})
    assert out


def test_catalog_details(call):
    fx = call("catalog", {"topic": "products", "category": "fx"})
    assert {p["name"] for p in fx["products"]} >= {"FXForward", "FXOption"}
    assert {p["pricing_tool"] for p in fx["products"]} >= {"qlrisk_price_fx_forward", "qlrisk_price_fx_option"}
    one = call("catalog", {"topic": "products", "name": "CorporateBond"})
    assert {"coupon_pct", "issuer", "maturity"} <= set(one["trade_schema"]["properties"]) and one["pricing_tool"] == "qlrisk_price_corporate_bond"
    cva = call("catalog", {"topic": "calculators", "name": "cva"})
    assert "ee_profile" in cva["input_schema"]["properties"] and "method" in cva["config"]
    md = call("catalog", {"topic": "market_data"})
    assert "EQ.SPX" in md["risk_factors"]
    assert "Currency" in call("catalog", {"topic": "enumerations"})
    assert call("catalog", {"topic": "processes"})["processes"]


# ── pricing and sensitivities ───────────────────────────────────────

def test_price_trades(call):
    out = call("price_trades", {"trades": BOOK, "include_cash_flows": True})
    assert len(out["trades"]) == 5 and not out["errors"]
    assert finite(out["total_npv"])
    fx = next(t for t in out["trades"] if t["trade_id"] == "EURUSD-C")
    assert fx["npv"] > 0
    assert math.isclose(out["total_npv"], sum(t["npv_reporting"] for t in out["trades"]))


def test_price_with_market_overrides_and_shocks(call):
    base = call("price_trades", {"trades": [SWAP]})["total_npv"]
    up = call("price_trades", {"trades": [SWAP], "market_data": {"shocks": [
        {"curve_field": "forward_curves", "curve_name": "SOFR", "shape": "parallel", "size": 0.01},
        {"curve_field": "discount_curve", "shape": "parallel", "size": 0.01}]}})["total_npv"]
    assert up > base                                       # payer swap gains when rates rise
    custom = call("price_trades", {"trades": [SWAP], "market_data": {"valuation_date": "2026-10-09",
                                                                     "forward_curves": {"SOFR": {"1Y": 0.05, "10Y": 0.05}}}})
    assert custom["valuation_date"] == "2026-10-09"


def test_sensitivities(call):
    out = call("sensitivities", {"trades": [SWAP, BOND, EQO], "ladder_vertices": "frtb_girr",
                                 "cross_gamma_factors": ["EQ.SPX", "VOL.eq_vol.1Y"]})
    measures = {(r["risk_class"], r["measure"]) for r in out["by_risk_class"]}
    assert ("IR", "dv01") in measures and ("CR", "cs01") in measures and ("EQ", "delta") in measures
    assert out["ladders"] and out["theta"] and out["cross_gamma"]
    only_ir = call("sensitivities", {"trades": [SWAP], "risk_classes": ["IR"], "include_ladders": False,
                                     "bump_method": "forward", "include_theta": False})
    assert {r["risk_class"] for r in only_ir["by_risk_class"]} == {"IR"}


# ── market risk ─────────────────────────────────────────────────────

@pytest.mark.parametrize("method", ["historical", "age_weighted", "filtered_historical", "monte_carlo", "parametric"])
def test_value_at_risk_methods(call, method):
    out = call("value_at_risk", {"trades": [SWAP, EQO], "method": method, "mc_paths": 1000, "history": SHORT_HISTORY})
    assert out["var"]["value"] > 0 and out["es"]["value"] > 0


def test_value_at_risk_extras(call):
    out = call("value_at_risk", {"trades": [SWAP, EQO, BOND], "horizon_days": 10, "include_stressed_var": True,
                                 "revaluation": "taylor", "group_by": {"IRS-5Y": "rates", "SPX-P": "equity", "ACME-5Y": "credit"},
                                 "liquidity": {"spreads": {"ACME-5Y": 0.004}, "horizon_days": 5}})
    assert out["stressed_var"]["value"] > 0
    assert set(out["decomposition"]["component"]) == {"IRS-5Y", "SPX-P", "ACME-5Y"}
    assert set(out["decomposition"]["by_group"]) == {"rates", "equity", "credit"}
    assert out["liquidity"]["liquidity_adjusted_var"] > out["var"]["value"]


def test_value_at_risk_pnl_series(call):
    pnl = [math.sin(i) * 1000 for i in range(250)]
    out = call("value_at_risk", {"mode": "pnl_series", "pnl": pnl, "confidence_pct": 99, "horizon_days": 10})
    assert out["var"] > 0 and math.isclose(out["var"], out["var_1d"] * math.sqrt(10))
    assert "at least 10" in call("value_at_risk", {"mode": "pnl_series", "pnl": [1, 2]}, ok=False)


def test_backtest_modes(call):
    out = call("backtest", {"trades": [SWAP, EQO], "test_days": 100, "include_series": True})
    assert out["var"]["zone"] in ("green", "amber", "red") and out["pla"]["zone"] and len(out["series"]["hpl"]) == 100
    pnl = [math.sin(i) * 1000 for i in range(250)]
    var = [900.0] * 250
    v = call("backtest", {"mode": "var_series", "pnl": pnl, "var_forecasts": var})
    assert v["var"]["n"] == 250 and "hits" not in v["var"]
    e = call("backtest", {"mode": "es_series", "pnl": pnl, "var_forecasts": var, "es_forecasts": [950.0] * 250})
    assert e["es"]["zone"]
    p = call("backtest", {"mode": "pla", "hpl": pnl, "rtpl": [x * 0.98 for x in pnl]})
    assert p["pla"]["zone"] == "green"


def test_pnl_explain(call):
    out = call("pnl_explain", {"trades": [EQO, SWAP], "end_shocks": [{"factor": "EQ.SPX", "size": -0.05, "shock_type": "relative"}],
                               "end_valuation_date": (date.today() + timedelta(days=1)).isoformat()})
    eq = next(t for t in out["trades"] if t["trade_id"] == "SPX-P")
    assert eq["actual"] > 0 and eq["by_risk_class"]["EQ"] > 0             # a long put gains when SPX falls
    assert "actual" in out["total"]
    assert "end_market_data" in call("pnl_explain", {"trades": [SWAP]}, ok=False)


def test_stress_modes(call):
    lib = call("stress_test", {"trades": BOOK})
    assert len(lib["results"]) >= 9 and lib["worst"] == lib["results"][0]["scenario"]
    sub = call("stress_test", {"trades": BOOK, "scenarios": ["2020_covid"]})
    assert [r["scenario"] for r in sub["results"]] == ["2020_covid"]
    cus = call("stress_test", {"trades": [SWAP], "mode": "custom", "custom_scenarios": [
        {"name": "rates +100bp", "shocks": [{"risk_classes": ["IR"], "shape": "parallel", "size": 0.01}]},
        {"name": "steepener", "shocks": [{"curve_field": "forward_curves", "curve_name": "SOFR", "shape": "twist",
                                          "short_end": -0.0025, "long_end": 0.0025}]},
        {"name": "risk off", "definition": {"equity": -0.2, "credit": 0.5, "rates": -0.005}}]})
    assert {r["scenario"] for r in cus["results"]} == {"rates +100bp", "steepener", "risk off"}
    rev = call("stress_test", {"trades": [SWAP, EQO], "mode": "reverse", "target_loss": 500_000, "history": SHORT_HISTORY})
    assert rev["achieved_loss"] == pytest.approx(500_000, rel=0.05) and rev["sigma_distance"] > 0
    assert "is not one of" in call("stress_test", {"trades": [SWAP], "scenarios": ["1929"]}, ok=False)


# ── regulatory capital ──────────────────────────────────────────────

def test_frtb_sa(call):
    out = call("frtb_sa_capital", {"trades": BOOK, "credit_buckets": {"ACME": 4, "GLOBEX": 12}, "equity_buckets": {"SPX": 12},
                                   "ratings": {"ACME": "BBB", "GLOBEX": "BB"}, "vol_underlyings": {"eq_vol": "SPX", "fx_vol": "EURUSD"}})
    assert out["total"] > 0 and out["sbm"]["total"] > 0 and out["summary"]["TOTAL"] == pytest.approx(out["total"])
    sbm = call("frtb_sa_capital", {"mode": "sbm_from_sensitivities", "frtb_sensitivities": [
        {"risk_class": "GIRR", "risk_type": "delta", "bucket": "USD", "name": "SOFR", "tenor": 5.0, "sensitivity": 2e7, "risk_weight": 0.0078},
        {"risk_class": "EQ", "risk_type": "delta", "bucket": 12, "name": "SPX", "tenor": None, "sensitivity": -3e6, "risk_weight": 0.15}]})
    assert sbm["sbm"]["total"] > 0
    drc = call("frtb_sa_capital", {"mode": "drc_from_positions", "drc_positions": [
        {"obligor": "ACME", "rating": "BBB", "notional": 10e6, "market_value": 9.9e6, "maturity": 5.0}]})
    assert drc["drc"]["total"] > 0


def test_frtb_ima_modes(call):
    d0 = date(2026, 10, 9)
    full = call("frtb_ima_capital", {"trades": [SWAP, BOND, CDS], "history": {"num_days": 600, "stress_start": 200, "stress_days": 50},
                                     "nmrf": ["CR.GLOBEX.5Y"], "ratings": {"ACME": "BBB", "GLOBEX": "BB"}, "n_sims": 20000})
    assert full["capital"] > 0 and full["imcc"]["imcc"] > 0 and full["ses"]["ses"] > 0
    imcc = call("frtb_ima_capital", {"mode": "imcc", "trades": [SWAP], "history": {"num_days": 600, "stress_start": 200, "stress_days": 50}})
    assert imcc["imcc"]["ratio"] >= 1.0
    lh = call("frtb_ima_capital", {"mode": "lh_es", "trades": [SWAP], "history": SHORT_HISTORY})
    assert lh["es"] > 0 and lh["components"]
    hz = call("frtb_ima_capital", {"mode": "liquidity_horizons"})
    assert set(hz["liquidity_horizons"].values()) <= {10, 20, 40, 60, 120}
    rf = call("frtb_ima_capital", {"mode": "rfet", "as_of": d0.isoformat(), "observations": {
        "dense": [(d0 - timedelta(days=i)).isoformat() for i in range(0, 360, 3)],
        "sparse": [(d0 - timedelta(days=i)).isoformat() for i in range(0, 360, 20)]}})
    assert rf["modellable"] == {"dense": True, "sparse": False}
    drc = call("frtb_ima_capital", {"mode": "ima_drc", "n_sims": 20000, "drc_positions": [
        {"obligor": "ACME", "rating": "BBB", "notional": 10e6, "market_value": 10e6, "maturity": 5.0}]})
    assert drc["drc"]["drc"] == pytest.approx(7.5e6)
    cap = call("frtb_ima_capital", {"mode": "capital", "imcc": 10.0, "ses": 2.0, "drc": 1.0})
    assert cap["capital"] == pytest.approx(18.0)


def test_basel25(call):
    out = call("basel25_capital", {"var_series": [1e6] * 60, "svar_series": [2e6] * 60, "exceptions": 0})
    assert out["result"]["capital"] == pytest.approx(9e6)
    book = call("basel25_capital", {"trades": [SWAP, EQO]})
    assert book["result"]["capital"] > 0 and book["svar_10d"] > 0
    assert "var_series" in call("basel25_capital", {}, ok=False)


# ── counterparty credit risk ────────────────────────────────────────

def test_ccr_exposure_modes(call):
    prof = call("ccr_exposure", {"trades": [SWAP, FXO], "num_scenarios": 500})
    row = prof["trades"][0]
    assert row["peak_exposure"] >= 0 and len(row["expected_exposure"]) == len(row["time_grid"])
    for m, inputs in {
        "ce": {"mark_to_market": 1.5e6, "collateral_held": 5e5},
        "ee": {"current_mtm": 1e5, "notional": 1e7, "remaining_maturity": 5, "volatility": 0.01},
        "eee": {"current_mtm": 1e5, "notional": 1e7, "remaining_maturity": 5, "volatility": 0.01},
        "pfe": {"current_mtm": 1e5, "notional": 1e7, "remaining_maturity": 5, "volatility": 0.01},
        "peak": {"current_mtm": 1e5, "notional": 1e7, "remaining_maturity": 5, "volatility": 0.01},
        "stressed": {"current_mtm": 1e5, "notional": 1e7, "remaining_maturity": 5, "volatility": 0.01},
    }.items():
        out = call("ccr_exposure", {"mode": "calculator", "measure": m, "inputs": inputs, "config": {}})
        assert out["measure"] == m and finite(out["headline"]), (m, out)
    ww = call("ccr_exposure", {"mode": "wrong_way", "trades": [CDS, SWAP], "credit_factor": "CR.GLOBEX.5Y", "history": SHORT_HISTORY})
    assert finite(ww["ratio"]) and ww["conditional_exposure"] >= 0
    assert "unknown field" in call("ccr_exposure", {"mode": "calculator", "measure": "ce", "inputs": {"mtm": 1}}, ok=False)
    assert "unknown key" in call("ccr_exposure", {"mode": "calculator", "measure": "ce",
                                                  "inputs": {"mark_to_market": 1}, "config": {"colour": 1}}, ok=False)


def test_saccr_modes(call):
    ns = call("saccr", {"trades": [SWAP, FXO, CDS], "csa": {"BANK-A": {"margined": True, "collateral": 0.0, "threshold": 0}}})
    assert set(ns["netting_sets"]) == {"BANK-A", "BANK-B"} and ns["ead_total"] > 0
    tr = call("saccr", {"mode": "trades", "trades": [SWAP, FXO]})
    assert all(r["ead"] > 0 for r in tr["trades"])
    calc = call("saccr", {"mode": "calculator", "calculator_input": {"netting_set_id": "NS1", "trades": [
        {"asset_class": "interest_rate", "notional": 1e7, "maturity": 5, "mtm": 1e5}]}})
    assert calc["headline"] > 0


def test_initial_margin(call):
    one = call("initial_margin", {"method": "simm", "positions": [{"notional": 1e7, "product_type": "irs",
                                                                     "remaining_maturity": 5, "delta_sensitivities": {"5y": 4500}}]})
    assert one["headline"] == pytest.approx(56 * 4500)          # ISDA SIMM: 5y risk weight 56bp x DV01 per bp
    bad = call("initial_margin", {"method": "simm", "positions": [{"notional": 1e7, "product_type": "irs",
                                                                   "remaining_maturity": 5, "delta_sensitivities": {"USD-5Y": 4500}}]}, ok=False)
    assert "'USD-5Y' is not a SIMM rates bucket" in bad
    sched = call("initial_margin", {"method": "schedule", "positions": [{"notional": 1e7, "product_type": "irs", "remaining_maturity": 5}]})
    assert sched["headline"] == pytest.approx(160_000)
    port = call("initial_margin", {"method": "schedule", "positions": [
        {"notional": 1e7, "product_type": "irs", "remaining_maturity": 5},
        {"notional": 5e6, "product_type": "fx_forward", "remaining_maturity": 1}]})
    assert port["headline"] > 0


@pytest.mark.parametrize("measure,inputs,config", [
    ("pd", {"credit_rating": "BBB"}, {"model": "transition_matrix"}),
    ("pd", {"asset_value": 120, "debt_value": 100, "asset_volatility": 0.25, "risk_free_rate": 0.04}, {"model": "structural"}),
    ("lgd", {"exposure": 1e6, "recovery_rate": 0.4}, {"model": "fixed"}),
    ("ead", {"current_exposure": 1e6, "notional": 1e7}, {}),
    ("el", {"pd": 0.02, "lgd": 0.45, "ead": 1e6}, {}),
    ("economic_capital", {"exposures": [1e6, 2e6], "pds": [0.01, 0.02], "lgds": [0.45, 0.45]}, {"method": "vasicek"}),
    ("raroc", {"revenue": 5e5, "operating_cost": 1e5, "expected_loss": 2e4, "economic_capital": 1e6}, {}),
])
def test_credit_risk(call, measure, inputs, config):
    out = call("credit_risk", {"measure": measure, "inputs": inputs, "config": config})
    assert finite(out["headline"])
    if measure == "el":
        assert out["headline"] == pytest.approx(9000)


def test_credit_risk_errors(call):
    assert "must be one of" in call("credit_risk", {"measure": "pd", "inputs": {"credit_rating": "BBB"}, "config": {"model": "magic"}}, ok=False)


def test_xva(call):
    for m, inputs in {
        "cva": {"ee_profile": EE, "time_grid": TG, "credit_spread": 0.012},
        "dva": {"exposure_profile": [-x for x in EE], "time_grid": TG, "own_pd_curve": {"1": 0.01, "5Y": 0.015}},
        "fva": {"exposure_profile": EE, "time_grid": TG, "funding_spread": 0.01},
        "kva": {"ead_profile": EE, "time_grid": TG},
        "mva": {"initial_margin_profile": EE, "time_grid": TG},
    }.items():
        out = call("xva", {"measure": m, "inputs": inputs})
        assert out["headline"] > 0, (m, out)
    total = call("xva", {"measure": "total", "inputs": {"cva": {"ee_profile": EE, "time_grid": TG, "credit_spread": 0.012},
                                                        "fva": {"exposure_profile": EE, "time_grid": TG}, "colva": 1500.0}})
    c = total["components"]
    assert c["total_xva"] == pytest.approx(c["cva"] + c["fva"] + 1500.0)
    sa = call("xva", {"measure": "sa_cva", "counterparty": "ACME", "time_grid": TG, "expected_exposure": EE,
                      "counterparty_buckets": {"ACME": ["3", True]}})
    hedged = call("xva", {"measure": "sa_cva", "counterparty": "ACME", "time_grid": TG, "expected_exposure": EE,
                          "counterparty_buckets": {"ACME": ["3", True]},
                          "hedges": [{"product": "CreditDefaultSwap", "trade_id": "H", "notional": 3e6, "maturity": "5Y",
                                      "reference": "ACME", "counterparty_id": "DEALER"}]})
    assert sa["capital"] > hedged["capital"] > 0
    ba = call("xva", {"measure": "ba_cva", "counterparties": [
        {"name": "BANK", "sector": "financial", "investment_grade": True, "netting_sets": [[10e6, 5.0]]}]})
    df = (1 - math.exp(-0.25)) / 0.25
    assert ba["result"]["capital"] == pytest.approx(0.65 * 0.05 / 1.4 * 5.0 * 10e6 * df)
    assert "credit curve" in call("xva", {"measure": "sa_cva", "counterparty": "NOBODY", "time_grid": TG,
                                          "expected_exposure": EE, "counterparty_buckets": {"NOBODY": ["3", True]}}, ok=False)


# ── paths, report, limits ───────────────────────────────────────────

def test_simulate_every_process(call):
    from sajha.tools.impl.qlrisk.introspect import supported_processes
    assert len(supported_processes()) >= 7
    for proc in supported_processes():
        start = 100.0 if proc in ("gbm", "heston", "merton_jump") else 0.03
        out = call("simulate_paths", {"process": proc, "initial_value": start, "long_term_mean": 0.03,
                                      "num_paths": 500, "num_steps": 50, "sample_paths": 2})
        assert out["num_paths"] == 500 and len(out["sample_paths"]) == 2 and len(out["time_grid"]) <= 60
        assert finite(out["terminal"]["mean"])
    gbm = call("simulate_paths", {"process": "gbm", "initial_value": 100, "drift": 0.05, "volatility": 0.2,
                                  "maturity": 1, "num_steps": 252, "num_paths": 10000})
    assert gbm["terminal"]["mean"] == pytest.approx(100 * math.exp(0.05), rel=0.02)


def test_risk_report(call):
    demo = call("risk_report", {"use_demo_book": True, "limits": [{"name": "Firm 1d VaR", "metric": "var.1d", "limit": 500000}]})
    assert {"pv.total", "var.1d", "es.1d", "frtb_sa.total"} <= set(demo["metrics"])
    assert demo["limits"][0]["name"] == "Firm 1d VaR" and demo["stress"]
    own = call("risk_report", {"trades": [SWAP, EQO], "measures": ["PV", "VAR", "ES", "EXPOSURE"],
                               "hierarchy": {"levels": ["desk"], "paths": {"IRS-5Y": ["Rates"], "SPX-P": ["Equity"]}}})
    assert "Rates" in own["by_node"] and own["netting_sets"]
    assert "not both" in call("risk_report", {"use_demo_book": True, "trades": [SWAP]}, ok=False)


def test_check_limits(call):
    out = call("check_limits", {"metrics": {"var.1d": 420000, "es.1d": 700000},
                                "by_node": {"Rates": {"var.1d": 300000}},
                                "limits": [{"name": "Firm VaR", "metric": "var.1d", "limit": 500000},
                                           {"name": "Firm ES", "metric": "es.1d", "limit": 600000},
                                           {"name": "Rates VaR", "metric": "var.1d", "limit": 1000000, "node": "Rates"}]})
    status = {c["name"]: c["status"] for c in out["checks"]}
    assert status == {"Firm VaR": "amber", "Firm ES": "breach", "Rates VaR": "green"}
    assert out["breaches"] == ["Firm ES"]


# ── end to end: REST and /mcp on the app ────────────────────────────

@pytest.fixture(scope="module")
def app_client():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post("/api/auth/login", json={"user_id": "admin", "password": "admin123"})
        assert r.status_code == 200, r.text
        yield c, {"Authorization": f"Bearer {r.json()['token']}"}


def test_rest_lists_and_executes_qlrisk_tools(app_client):
    c, h = app_client
    listed = c.get("/api/tools/list", headers=h).json()
    names = {t["name"] for t in (listed.get("tools", listed) if isinstance(listed, dict) else listed)}
    assert {"qlrisk_" + n for n in NAMES} <= names
    r = c.post("/api/tools/execute", headers=h, json={"tool": "qlrisk_price_trades", "arguments": {"trades": [SWAP]}})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["trades"][0]["trade_id"] == "IRS-5Y"
    r = c.post("/api/tools/execute", headers=h, json={"tool": "qlrisk_value_at_risk",
                                                       "arguments": {"trades": [SWAP], "advanced": {"history": SHORT_HISTORY}}})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["var"]["value"] > 0
    bad = c.post("/api/tools/execute", headers=h, json={"tool": "qlrisk_price_trades", "arguments": {"trades": [{"product": "Nope"}]}})
    assert bad.status_code == 400 and "not one of" in bad.json()["error"]


def test_mcp_calls_qlrisk_tools_with_structured_content_and_a_summary(app_client):
    c, h = app_client
    r = c.post("/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}}})
    sh = dict(h, **{"Mcp-Session-Id": r.headers["mcp-session-id"], "MCP-Protocol-Version": "2025-11-25",
                    "Accept": "application/json"})
    listed, cursor = {}, None
    while True:                                                         # tools/list is paginated
        r = c.post("/mcp", headers=sh, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                             "params": {"cursor": cursor} if cursor else {}})
        page = r.json()["result"]
        listed.update({t["name"]: t for t in page["tools"]})
        cursor = page.get("nextCursor")
        if not cursor:
            break
    assert listed["qlrisk_value_at_risk"]["annotations"]["readOnlyHint"] is True
    assert listed["qlrisk_price_trades"]["inputSchema"]["properties"]["trades"]["maxItems"] >= 1
    for rid, (name, args, word) in enumerate([("qlrisk_price_trades", {"trades": [SWAP]}, "total NPV"),
                                              ("qlrisk_value_at_risk", {"trades": [SWAP], "advanced": {"history": SHORT_HISTORY}}, "VaR")], 3):
        r = c.post("/mcp", headers=sh, json={"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                                             "params": {"name": name, "arguments": args}})
        res = r.json()["result"]
        assert not res.get("isError"), res
        summary = res["content"][0]["text"].split("\n", 1)[0]
        assert word in summary and isinstance(res["structuredContent"], dict)


# ── per-product pricing tools (generated) ───────────────────────────

def test_generated_product_configs_are_up_to_date():
    """Fails when qlrisk's products changed: run python -m sajha.tools.impl.qlrisk.generate to regenerate."""
    from sajha.tools.impl.qlrisk import generate
    assert generate.differences() == []


def test_one_product_tool_per_priceable_product(product_tools):
    from sajha.tools.impl.qlrisk import generate, introspect as I
    from sajha.tools.impl.qlrisk.tools.products import tool_name
    configs, skipped = generate.build()
    assert {tool_name(p) for p in I.product_classes()} == set(product_tools) | {tool_name(p) for p, _ in skipped}
    assert len(product_tools) == len(configs) and "qlrisk_price_trades" not in product_tools
    assert tool_name("InterestRateSwap") == "qlrisk_price_interest_rate_swap"
    assert tool_name("FXOption") == "qlrisk_price_fx_option" and tool_name("MTMCrossCurrencySwap") == "qlrisk_price_mtm_cross_currency_swap"


CALL_NAMES = {"market_data", "reporting_currency", "include_cash_flows"}
NOTIONAL_NAMES = ("face_value", "principal", "position_value", "notional", "base_notional")
MD = {"valuation_date": "2026-10-09"}


def _run(tool, args, md=MD):
    adv = {**args.get("advanced", {}), "market_data": md}
    return tool.execute_with_tracking({**args, "advanced": adv})


def test_every_product_tool_schema_is_valid_and_its_example_validates(product_tools):
    import jsonschema
    from sajha.tools.impl.qlrisk.tools.products import exposed_fields
    for name, (tool, cfg) in product_tools.items():
        schema = tool.input_schema
        jsonschema.Draft202012Validator.check_schema(schema)
        assert "__" not in name and cfg["requires"] == ["qlrisk"] and "inputSchema" not in cfg
        assert schema["additionalProperties"] is False and "product" not in schema["properties"]
        own = {e.name for e in exposed_fields(cfg["product"]) if not e.advanced}
        assert set(schema["properties"]) == own | {"advanced"}, name
        adv = schema["properties"]["advanced"]
        assert "advanced" not in schema.get("required", []) and adv["additionalProperties"] is False
        assert CALL_NAMES <= set(adv["properties"]), name
        # the clutter lives in advanced, never on the main form
        for clutter in ("trade_id", "trade_date", "effective_date", "counterparty_id", "issuer", "position",
                        "tenor_years", "maturity_date", "coupon") + tuple(CALL_NAMES):
            assert clutter not in schema["properties"], (name, clutter)
        for e in exposed_fields(cfg["product"]):
            assert e.schema.get("title"), (name, e.name)
            if e.spec.unit == "percent":
                assert e.name.endswith("_pct"), (name, e.name)
            if e.spec.unit == "basis points":
                assert e.name.endswith("_bp"), (name, e.name)
        example = cfg["metadata"]["example"]
        lines = cfg["description"].split("\n")
        assert len(lines) == 3 and lines[1].startswith("Inputs") and json.dumps(example) in lines[2]
        tool.validate_arguments(example)
        assert tool.to_mcp_format()["annotations"]["readOnlyHint"] is True


def _amount(example, schema):
    for n in NOTIONAL_NAMES:
        if n in example:
            return example[n]
        if n in schema["properties"] and "default" in schema["properties"][n]:
            return schema["properties"][n]["default"]
    raise AssertionError("no notional")


def test_every_product_example_prices_plausibly(product_tools):
    """Each generated example prices to its recorded result and to a plausible value for its asset class."""
    from sajha.tools.impl.qlrisk import introspect as I
    for name, (tool, cfg) in product_tools.items():
        example, product = cfg["metadata"]["example"], cfg["product"]
        out = _run(tool, example)
        assert out["npv"] == pytest.approx(cfg["metadata"]["example_result"]["npv"], abs=0.01), name
        assert finite(out["npv"]) and finite(out["npv_reporting"]) and out["product"] == product
        amount = _amount(example, tool.input_schema)
        spec = I.product_spec(product)
        pricer, ratio = spec["pricer"], out["npv"] / amount
        if pricer in ("price_fixed_bond", "price_frn", "price_convertible", "price_abs", "price_mbs"):
            assert 0.70 <= ratio <= 1.30, (name, out["npv"])          # a near-par bond: 70-130% of face
        elif pricer in ("price_deposit", "price_cash_equity"):
            assert 0.70 <= ratio <= 1.30, (name, out["npv"])
        elif spec["category"] == "sft":
            assert abs(ratio) <= 1.50, (name, out["npv"])             # a loan or financing: about its principal
        elif pricer in ("price_tranche", "price_clo_tranche"):
            assert 0.0 <= ratio <= 1.10, (name, out["npv"])           # a risky tranche: at most par-ish
        elif "option" in pricer or pricer in ("price_fx_digital", "price_fx_barrier") or \
                product in ("InterestRateCap", "InterestRateFloor", "Swaption"):
            assert 0.0 <= ratio <= 1.0, (name, out["npv"])            # a long option: non-negative
        else:
            assert abs(ratio) <= 0.30, (name, out["npv"])             # swaps, forwards, futures near the money


def test_owner_case_treasury_bond_3y_3pct(product_tools):
    """The bug report: maturity 3Y, face 100, coupon 3 (percent), USD prices a 3-year 3% bond near par."""
    tool, cfg = product_tools["qlrisk_price_treasury_bond"]
    out = _run(tool, {"maturity": "3Y", "face_value": 100, "coupon_pct": 3, "currency": "USD"})
    assert 95 <= out["npv"] <= 100 and out["npv"] == pytest.approx(97.85, abs=0.01)
    assert out["qlrisk_terms"]["coupon"] == 0.03 and out["qlrisk_terms"]["frequency"] == 2
    assert out["qlrisk_terms"]["maturity_date"] == "2029-10-09" and out["qlrisk_terms"]["notional"] == 100
    assert "97.85" in cfg["description"].split("\n")[2]
    props = tool.input_schema["properties"]
    assert list(props)[:3] == ["maturity", "face_value", "coupon_pct"] and props["frequency"]["default"] == "semi-annual"
    assert props["currency"]["default"] == "USD" and tool.input_schema["required"] == ["maturity", "coupon_pct"]


def test_rates_out_of_bounds_are_clear_errors(product_tools):
    from sajha.tools.base_mcp_tool import ToolArgumentError
    bond, _ = product_tools["qlrisk_price_treasury_bond"]
    with pytest.raises(ToolArgumentError, match="coupon_pct"):
        _run(bond, {"maturity": "3Y", "coupon_pct": 300})
    with pytest.raises(ToolArgumentError, match="coupon_pct"):
        _run(bond, {"maturity": "3Y", "coupon_pct": -1})
    with pytest.raises(ToolArgumentError, match="face_value"):
        _run(bond, {"maturity": "3Y", "coupon_pct": 3, "face_value": 0})
    with pytest.raises(ToolArgumentError, match="coupon_pct"):
        _run(bond, {"maturity": "3Y"})
    # the code-level check (for callers that skip schema validation) names the field and the unit
    from sajha.tools.impl.qlrisk.inputs import InvalidInput
    from sajha.tools.impl.qlrisk.tools.products import to_trade
    with pytest.raises(InvalidInput, match=r"coupon_pct: 300 is outside 0.0 to 100.0 percent \(rates are in percent"):
        to_trade("TreasuryBond", {"maturity": "3Y", "coupon_pct": 300}, date(2026, 10, 9), [])
    warnings = []
    to_trade("TreasuryBond", {"maturity": "3Y", "coupon_pct": 0.03}, date(2026, 10, 9), warnings)
    assert any("for 3% send 3" in w for w in warnings)
    cds, _ = product_tools["qlrisk_price_credit_default_swap"]
    with pytest.raises(ToolArgumentError, match="recovery_pct"):
        _run(cds, {"maturity": "5Y", "reference": "GLOBEX", "recovery_pct": 100})
    cdo, _ = product_tools["qlrisk_price_cdo"]
    with pytest.raises(ToolArgumentError, match="detachment_pct: must be after attachment_pct"):
        _run(cdo, {"maturity": "5Y", "attachment_pct": 7, "detachment_pct": 3})


@pytest.mark.parametrize("value, expected", [("3Y", "2029-10-09"), ("18M", "2028-04-09"), ("6W", "2026-11-20"),
                                             ("10D", "2026-10-19"), ("1.5y", "2028-04-09"), ("2031-02-28", "2031-02-28")])
def test_maturity_takes_tenors_and_dates(product_tools, value, expected):
    tool, _ = product_tools["qlrisk_price_treasury_bond"]
    out = _run(tool, {"maturity": value, "coupon_pct": 3})
    assert out["qlrisk_terms"]["maturity_date"] == expected


def test_maturity_errors(product_tools):
    from sajha.tools.base_mcp_tool import ToolArgumentError
    tool, _ = product_tools["qlrisk_price_treasury_bond"]
    with pytest.raises(ToolArgumentError, match="maturity: '3X' is neither a tenor"):
        _run(tool, {"maturity": "3X", "coupon_pct": 3})
    with pytest.raises(ToolArgumentError, match="not after the valuation date"):
        _run(tool, {"maturity": "2020-01-01", "coupon_pct": 3})
    with pytest.raises(ToolArgumentError, match="whole number of months"):
        _run(tool, {"maturity": "1.5M", "coupon_pct": 3})


def test_advanced_section(product_tools):
    tool, _ = product_tools["qlrisk_price_corporate_bond"]
    base = {"maturity": "5Y", "face_value": 100, "coupon_pct": 5}
    plain = _run(tool, base)
    out = _run(tool, {**base, "advanced": {"issuer": "ACME", "position": "short", "trade_id": "ACME-5Y",
                                           "include_cash_flows": True, "reporting_currency": "EUR"}})
    assert out["trade_id"] == "ACME-5Y" and out["npv"] < 0 and "cash_flows" in out
    assert -out["npv"] < plain["npv"]                     # the issuer's credit spread lowers the price
    assert out["reporting_currency"] == "EUR" and out["npv_reporting"] != out["npv"]
    assert out["qlrisk_terms"]["is_long"] is False and out["qlrisk_terms"]["issuer"] == "ACME"
    from sajha.tools.base_mcp_tool import ToolArgumentError
    with pytest.raises(ToolArgumentError, match="Additional properties"):
        _run(tool, {**base, "issuer": "ACME"})            # issuer is in advanced, not on the main form


def test_product_tool_worked_examples(product_tools):
    """The guide's examples: the swap in percent, its par rate prices to zero, a payer swaption is non-negative."""
    swap, _ = product_tools["qlrisk_price_interest_rate_swap"]
    out = _run(swap, {"maturity": "5Y", "notional": 10_000_000, "fixed_rate_pct": 4.4})
    assert out["npv"] == pytest.approx(-22834.98, abs=0.01) and out["qlrisk_terms"]["fixed_rate"] == 0.044
    par = out["components"]["par_rate"] * 100
    at_money = _run(swap, {"maturity": "5Y", "notional": 10_000_000, "fixed_rate_pct": par})
    assert abs(at_money["npv"]) < 1e-6 * 10_000_000
    from sajha.tools.base_mcp_tool import ToolArgumentError
    with pytest.raises(ToolArgumentError, match="fixed_rate_pct"):
        _run(swap, {"maturity": "5Y"})
    with pytest.raises(ToolArgumentError, match="Additional properties"):
        _run(swap, {"maturity": "5Y", "fixed_rate_pct": 4, "fixed_rate": 0.04})
    swaption, _ = product_tools["qlrisk_price_swaption"]
    out = _run(swaption, {"expiry": "1Y", "swap_start": "1Y", "swap_end": "6Y", "strike_pct": 4,
                          "volatility_pct": 20, "swaption_type": "receiver"})
    assert out["npv"] >= 0 and out["qlrisk_terms"]["volatility"] == 0.2 and out["qlrisk_terms"]["is_payer"] is False
    with pytest.raises(ToolArgumentError, match="swap_end: must be after swap_start"):
        _run(swaption, {"expiry": "1Y", "swap_start": "6Y", "swap_end": "1Y", "strike_pct": 4})


# ── core tools: presentation, worked examples, plausibility against independent estimates ──

CORE_MD = {"valuation_date": "2026-10-09"}


def test_core_tools_present_essentials_first_with_titles_and_a_worked_example(tools):
    import jsonschema
    from sajha.tools.impl.qlrisk.tools.layout import LAYOUTS
    for name, tool in tools.items():
        key = name[len("qlrisk_"):]
        schema = tool.input_schema
        jsonschema.Draft202012Validator.check_schema(schema)
        props = schema["properties"]
        assert [k for k in props if k != "advanced"] == [k for k in LAYOUTS[key].essentials if k in props], name
        for k, v in list(props.items()) + list(props.get("advanced", {}).get("properties", {}).items()):
            assert v.get("title"), (name, k)
        for old in ("confidence", "es_confidence", "confidence_level", "recovery", "drc_confidence"):
            assert old not in props and old not in props.get("advanced", {}).get("properties", {}), (name, old)
        example = schema["examples"][0]
        tool.validate_arguments(example)
        out = tool.execute_with_tracking(example)
        assert isinstance(out, dict) and out.summary, name


def _black(fwd, strike, t, vol, df, call):
    from math import erf, log, sqrt
    n = lambda x: 0.5 * (1 + erf(x / sqrt(2)))
    d1 = (log(fwd / strike) + 0.5 * vol * vol * t) / (vol * sqrt(t))
    d2 = d1 - vol * sqrt(t)
    return df * (fwd * n(d1) - strike * n(d2) if call else strike * n(-d2) - fwd * n(-d1))


def test_option_price_matches_black_scholes(call):
    """An SPX put priced through qlrisk_price_trades equals Black-76 on its forward, vol and the curve rate."""
    from math import exp, log
    from datetime import date as _d
    from qlrisk.data import create_sample_market_data
    from qlrisk.products.base import curve_value
    out = call("price_trades", {"trades": [EQO], "market_data": CORE_MD})
    row = out["trades"][0]
    c = row["components"]
    t = (_d(2027, 4, 9) - _d(2026, 10, 9)).days / 365.25
    r = curve_value(create_sample_market_data(_d(2026, 10, 9)).discount_curve, t)
    expected = (EQO["notional"] / EQO["strike"]) * _black(c["forward"], c["strike"], t, c["vol"], exp(-r * t), False)
    assert row["npv"] == pytest.approx(expected, rel=1e-6) and row["npv"] > 0
    assert c["forward"] == pytest.approx(c["spot"] * exp(r * t), rel=0.02)            # small dividend yield


def test_var_is_consistent_with_parametric_and_es(call):
    stock = {"product": "CommonStock", "trade_id": "SPX-1M", "position_value": 1_000_000, "ticker": "SPX"}
    base = {"trades": [stock], "market_data": CORE_MD, "horizon_days": 1, "confidence_pct": 99, "es_confidence_pct": 99}
    hist = call("value_at_risk", {**base, "method": "historical"})
    para = call("value_at_risk", {**base, "method": "parametric"})
    assert hist["confidence"] == 0.99 and hist["horizon_days"] == 1
    assert 0.5 <= hist["var"]["value"] / para["var"]["value"] <= 2.0                  # same order as delta-normal
    assert hist["es"]["value"] >= hist["var"]["value"] * 0.999                         # ES >= VaR at one confidence
    assert 0 < para["var"]["value"] < 0.2 * stock["position_value"]                    # a 1-day 99% loss under 20%
    ten = call("value_at_risk", {**base, "method": "parametric", "horizon_days": 10})
    assert ten["var"]["value"] == pytest.approx(para["var"]["value"] * 10 ** 0.5, rel=0.25)   # square-root of time


def test_backtest_exceptions_match_the_series(call):
    out = call("backtest", {"trades": [SWAP, EQO], "market_data": CORE_MD, "include_series": True})
    s = out["series"]
    count = sum(1 for p, v in zip(s["hpl"], s["var"]) if p < -v)
    assert out["var"]["exceptions"] == count and out["var"]["n"] == len(s["hpl"]) == 250
    assert out["var"]["expected_exceptions"] == pytest.approx(2.5)
    assert out["var"]["zone"] == ("green" if count <= 4 else "amber" if count <= 9 else "red")


def test_saccr_ead_is_alpha_times_rc_plus_pfe(call):
    out = call("saccr", {"trades": [SWAP], "market_data": CORE_MD, "csa": {"BANK-A": {"margined": True, "threshold": 0}}})
    ns = out["netting_sets"]["BANK-A"]
    assert ns["ead"] == pytest.approx(1.4 * (ns["replacement_cost"] + ns["multiplier"] * ns["addon"]), rel=1e-9)
    # by hand (CRE52): SF 0.5% x supervisory duration x notional x margined MF 1.5 x sqrt(10/250)
    from math import exp, sqrt
    sd = (1 - exp(-0.05 * ns["trades"][0]["maturity"])) / 0.05
    assert ns["addon"] == pytest.approx(0.005 * sd * 10_000_000 * 1.5 * sqrt(10 / 250), rel=0.01)
    floor = 0.05 + 0.95 * exp(ns["mtm"] / (2 * 0.95 * ns["addon"]))
    assert ns["multiplier"] == pytest.approx(min(1.0, floor), rel=1e-6)


def test_cva_is_near_the_rough_estimate(call):
    """CVA ~ LGD x sum(EE x DF x marginal PD), PD from the spread over 1 - recovery."""
    from math import exp
    ee, tg, spread, rec, r = [400_000, 600_000, 700_000, 650_000, 500_000], [1, 2, 3, 4, 5], 0.01, 0.4, 0.05
    out = call("xva", {"measure": "cva", "inputs": {"ee_profile": ee, "time_grid": tg, "credit_spread": spread,
                                                     "recovery_rate": rec, "notional": 10_000_000}})
    h, prev, rough = spread / (1 - rec), 0.0, 0.0
    for e, t in zip(ee, tg):
        rough += (1 - rec) * e * exp(-r * t) * (exp(-h * prev) - exp(-h * t))
        prev = t
    assert 0.6 <= out["headline"] / rough <= 1.4
    assert out["result"]["cva_pct"] == pytest.approx(100 * out["headline"] / 10_000_000)


def test_stress_moves_a_stock_by_the_shock(call):
    out = call("stress_test", {"trades": [{"product": "CommonStock", "position_value": 1_000_000, "ticker": "SPX"}],
                               "market_data": CORE_MD, "mode": "custom",
                               "custom_scenarios": [{"name": "eq -10%", "shocks": [{"factor": "EQ.SPX", "size": -0.1,
                                                                                   "shock_type": "relative"}]}]})
    assert out["results"][0]["pnl"] == pytest.approx(-100_000, rel=1e-6)


def test_capital_and_credit_formulas(call):
    b = call("basel25_capital", {"var_series": [1_000_000], "svar_series": [2_000_000], "exceptions": 3})
    assert b["result"]["capital"] == pytest.approx(max(1e6, 3 * 1e6) + max(2e6, 3 * 2e6))       # green zone: m = 3
    el = call("credit_risk", {"measure": "el", "inputs": {"pd": 0.02, "lgd": 0.45, "ead": 1_000_000}})
    assert el["headline"] == pytest.approx(0.02 * 0.45 * 1_000_000)
    sa = call("frtb_sa_capital", {"trades": [SWAP, BOND, EQO], "market_data": CORE_MD, "credit_buckets": {"ACME": 4},
                                  "equity_buckets": {"SPX": 12}, "ratings": {"ACME": "BBB"}, "vol_underlyings": {"eq_vol": "SPX"}})
    s = sa["summary"]
    assert s["TOTAL"] == pytest.approx(s["SBM"] + s["DRC"] + s["RRAO"])
    # DRC by hand (MAR22): BBB risk weight 6% x jump-to-default (LGD 75% x face - loss already in the price)
    bond_pv = call("price_trades", {"trades": [BOND], "market_data": CORE_MD})["trades"][0]["npv"]
    jtd = 0.75 * BOND["face_value"] - (BOND["face_value"] - bond_pv)
    assert s["DRC"] == pytest.approx(0.06 * jtd, rel=0.02)


def test_exposure_simulation_and_limits_are_consistent(call):
    out = call("ccr_exposure", {"trades": [SWAP], "market_data": CORE_MD, "mode": "trade_profiles"})
    p = out["trades"][0]
    assert p["peak_exposure"] >= max(p["expected_exposure"]) >= p["epe"] > 0
    assert all(f >= e for f, e in zip(p["potential_future_exposure"], p["expected_exposure"]))
    assert any("gives no CVA" in w for w in out.get("warnings", []))                    # qlrisk leaves it at 0.0
    gbm = call("simulate_paths", {"process": "gbm", "initial_value": 100, "drift": 0.05, "volatility": 0.2,
                                  "maturity": 1, "num_paths": 10000})
    from math import exp, sqrt
    assert gbm["terminal"]["mean"] == pytest.approx(100 * exp(0.05), rel=0.01)
    assert gbm["terminal"]["std"] == pytest.approx(100 * exp(0.05) * sqrt(exp(0.04) - 1), rel=0.03)
    lim = call("check_limits", {"metrics": {"var.1d": 420_000}, "limits": [{"name": "VaR", "metric": "var.1d", "limit": 500_000}]})
    assert lim["checks"][0]["utilisation"] == pytest.approx(0.84) and lim["checks"][0]["status"] == "amber"


def test_pnl_explain_adds_up_and_report_is_coherent(call):
    out = call("pnl_explain", {"trades": [EQO], "market_data": CORE_MD,
                               "end_shocks": [{"factor": "EQ.SPX", "size": -0.05, "shock_type": "relative"}]})
    t = out["total"]
    explained = sum(v for k, v in t.items() if k not in ("actual", "theta", "unexplained"))
    assert t["actual"] == pytest.approx(t["theta"] + explained + t["unexplained"], rel=1e-9)
    assert t["actual"] > 0 and abs(t["unexplained"]) < 0.05 * abs(t["actual"])        # a put gains when SPX falls
    rep = call("risk_report", {"use_demo_book": True, "market_data": CORE_MD})
    h = rep["metrics"]
    assert 0.8 <= h["es.1d"] / h["var.1d"] <= 1.5 and h["svar.10d"] > h["var.1d"]


@pytest.mark.xfail(strict=True, reason="qlrisk issue (reported): schedule IM = NGR x gross x rate; BCBS-IOSCO "
                                       "uses (0.4 + 0.6 x NGR) x gross x rate")
def test_schedule_initial_margin_follows_bcbs_iosco(call):
    out = call("initial_margin", {"method": "schedule", "positions": [{"notional": 10_000_000, "product_type": "irs",
                                                                       "remaining_maturity": 3}]})
    assert out["headline"] == pytest.approx((0.4 + 0.6 * 0.4) * 0.02 * 10_000_000)


def test_core_descriptions_carry_their_worked_example_and_its_real_result(tools):
    """The configs' descriptions are rewritten from the layout examples; this keeps their figures true."""
    from sajha.tools.impl.qlrisk.tools.layout import example
    for name, tool in tools.items():
        key = name[len("qlrisk_"):]
        ex = example(key)
        desc = tool.config["description"]
        assert f"Example: {json.dumps(ex)} gives " in desc, name
        if key == "risk_report":
            continue
        args = json.loads(json.dumps(ex))
        if "market_data" in json.dumps(tool.input_schema):
            args.setdefault("advanced", {})["market_data"] = CORE_MD
        assert tool.execute_with_tracking(args).summary in desc, name
