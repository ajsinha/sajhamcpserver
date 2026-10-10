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
        try:
            res = tool.execute_with_tracking(args)
        except (ToolArgumentError, RuntimeError) as exc:
            assert not ok, str(exc)
            return str(exc)
        assert ok, f"expected an error, got {str(res)[:300]}"
        assert isinstance(res, dict)
        return res
    return _call


SWAP = {"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10_000_000, "tenor_years": 5,
        "fixed_rate": 0.044, "counterparty_id": "BANK-A"}
BOND = {"product": "CorporateBond", "trade_id": "ACME-5Y", "notional": 5_000_000, "tenor_years": 5, "coupon": 0.05,
        "issuer": "ACME", "counterparty_id": "ACME"}
CDS = {"product": "CreditDefaultSwap", "trade_id": "GLX-CDS", "notional": 5_000_000, "tenor_years": 5,
       "reference": "GLOBEX", "coupon": 0.01, "counterparty_id": "BANK-B"}
EQO = {"product": "EquityOption", "trade_id": "SPX-P", "notional": 1_000_000, "tenor_years": 0.5, "ticker": "SPX",
       "strike": 5000, "is_call": False, "counterparty_id": "BANK-B"}
FXO = {"product": "FXOption", "trade_id": "EURUSD-C", "notional": 2_000_000, "tenor_years": 1, "pair": "EURUSD",
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
    assert trade["currency"]["enum"] == [c.value for c in Currency]
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
    assert "missing" in call("price_trades", {"trades": [{"product": "InterestRateSwap", "notional": 1e6}]}, ok=False)
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
    assert {"coupon", "issuer"} <= set(one["product"]["terms"])
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
    out = call("value_at_risk", {"mode": "pnl_series", "pnl": pnl, "confidence": 0.99, "horizon_days": 10})
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
                                                                     "remaining_maturity": 5, "delta_sensitivities": {"USD-5Y": 4500}}]})
    assert one["headline"] > 0
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
                          "hedges": [{"product": "CreditDefaultSwap", "trade_id": "H", "notional": 3e6, "tenor_years": 5,
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
                                                       "arguments": {"trades": [SWAP], "history": SHORT_HISTORY}})
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
                                              ("qlrisk_value_at_risk", {"trades": [SWAP], "history": SHORT_HISTORY}, "VaR")], 3):
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


def test_every_product_tool_schema_is_valid_and_its_example_validates(product_tools):
    import jsonschema
    from sajha.tools.impl.qlrisk import introspect as I
    for name, (tool, cfg) in product_tools.items():
        schema = tool.input_schema
        jsonschema.Draft202012Validator.check_schema(schema)
        assert "__" not in name and cfg["requires"] == ["qlrisk"] and "inputSchema" not in cfg
        assert schema["additionalProperties"] is False and "product" not in schema["properties"]
        spec = I.product_spec(cfg["product"])
        own = set(spec["parameters"]) | set(spec["terms"]) | {"tenor_years", "market_data", "reporting_currency", "include_cash_flows"}
        assert set(schema["properties"]) <= own, name
        example = cfg["metadata"]["example"]
        assert json.dumps(example) in cfg["description"]
        tool.validate_arguments(example)
        assert tool.to_mcp_format()["annotations"]["readOnlyHint"] is True


def test_price_one_product_per_asset_class_through_its_tool(product_tools):
    by_class = {}
    for name, (tool, cfg) in product_tools.items():
        from sajha.tools.impl.qlrisk import introspect as I
        by_class.setdefault(I.product_spec(cfg["product"])["asset_class"], (tool, cfg))
    assert len(by_class) >= 5
    for asset_class, (tool, cfg) in by_class.items():
        out = tool.execute_with_tracking({**cfg["metadata"]["example"], "market_data": {"valuation_date": "2026-10-09"}})
        assert out["product"] == cfg["product"] and finite(out["npv"]) and finite(out["npv_reporting"]), asset_class
        assert cfg["product"] in tool.format_mcp_result(out)["content"][0]["text"].split("\n", 1)[0]


def test_product_tool_worked_examples(product_tools):
    """The bond and swap examples of the guide's "Per-product pricing tools" section."""
    md = {"valuation_date": "2026-10-09"}
    bond, _ = product_tools["qlrisk_price_corporate_bond"]
    out = bond.execute_with_tracking({"notional": 5_000_000, "tenor_years": 5, "coupon": 0.05, "issuer": "ACME",
                                      "include_cash_flows": True, "market_data": md})
    assert out["product"] == "CorporateBond" and out["npv"] > 0 and "cash_flows" in out
    swap, _ = product_tools["qlrisk_price_interest_rate_swap"]
    out = swap.execute_with_tracking({"notional": 10_000_000, "tenor_years": 5, "fixed_rate": 0.044, "market_data": md})
    assert out["npv"] == pytest.approx(-22834.98, abs=0.01)
    from sajha.tools.base_mcp_tool import ToolArgumentError
    with pytest.raises(ToolArgumentError, match="fixed_rate"):
        swap.execute_with_tracking({"notional": 1e6, "tenor_years": 5})
    with pytest.raises(ToolArgumentError, match="Additional properties"):
        swap.execute_with_tracking({"notional": 1e6, "tenor_years": 5, "fixed_rate": 0.04, "strike": 1})
