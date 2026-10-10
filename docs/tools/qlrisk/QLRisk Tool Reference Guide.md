# QLRisk Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Common inputs](#common-inputs)
5. [Tools](#tools)
6. [Per-product pricing tools](#per-product-pricing-tools)
7. [Calling the Tools](#calling-the-tools)
8. [Limits](#limits)
9. [What is not wrapped](#what-is-not-wrapped)
10. [Troubleshooting](#troubleshooting)

---

## Overview

qlrisk is Ashutosh Sinha's risk-analytics library (QuantLib, numpy, scipy): pricing, sensitivities, market
risk, regulatory capital, counterparty credit risk and XVA on one product library. SAJHA ships its tools as
**native tools** in the tool folder `config/tools/qlrisk/`, named `qlrisk_<tool>`, implemented in
`sajha/tools/impl/qlrisk/` and run inside SAJHA like every other tool (access, policies, approvals, audit,
cache, metrics). qlrisk itself is an **optional dependency**: it is not on PyPI and not in
`requirements.txt`, and until it is installed the tools are skipped ([Setup](#setup)).

The tools are coarse-grained: one tool per kind of question, with a `mode` or `measure` where a question
has variants. The live list is the catalog (`tools/list`, or the Tools page); this guide documents each.

| Tool | Purpose |
|------|---------|
| `qlrisk_catalog` | Discover products and their terms, calculators and their inputs, stress scenarios, processes, market-data keys, enumerations |
| `qlrisk_price_trades` | NPV, pricing components and analytic Greeks of trades |
| `qlrisk_sensitivities` | DV01, CS01, delta, gamma, vega, theta, key-rate ladders, cross-gamma |
| `qlrisk_value_at_risk` | Historical, age-weighted, filtered, Monte Carlo and parametric VaR and ES; stressed VaR; decomposition; liquidity VaR |
| `qlrisk_backtest` | VaR and ES backtests (Kupiec, Christoffersen, traffic light, Acerbi-Szekely) and the FRTB PLA test |
| `qlrisk_pnl_explain` | Actual P&L split into theta, risk classes, factors and unexplained |
| `qlrisk_stress_test` | Historical crisis library, custom scenarios, reverse stress |
| `qlrisk_frtb_sa_capital` | FRTB SA: SBM delta / vega / curvature, DRC, RRAO |
| `qlrisk_frtb_ima_capital` | FRTB IMA: LH-adjusted ES, IMCC, RFET, SES, IMA DRC, capital |
| `qlrisk_basel25_capital` | Basel 2.5 VaR + SVaR capital |
| `qlrisk_ccr_exposure` | Exposure profiles (EE, PFE, EEE, EPE, peak), exposure calculators (CE, EE, EEE, PFE, peak, stressed), wrong-way risk |
| `qlrisk_saccr` | SA-CCR EAD per netting set (CRE52), per trade, or from trade summaries |
| `qlrisk_initial_margin` | ISDA SIMM, schedule or VaR initial margin |
| `qlrisk_credit_risk` | PD, LGD, EAD, EL, economic capital, RAROC |
| `qlrisk_xva` | CVA, DVA, FVA, KVA, MVA, a total with ColVA, SA-CVA and BA-CVA capital |
| `qlrisk_simulate_paths` | Monte Carlo paths of qlrisk's stochastic processes |
| `qlrisk_risk_report` | Every risk in one call with qlrisk's `RiskEngine`, rolled up a hierarchy, with limit checks |
| `qlrisk_check_limits` | Limit utilisation and status for figures you already have |
| `qlrisk_price_<product>` | One pricing tool per qlrisk product, with only that product's fields ([Per-product pricing tools](#per-product-pricing-tools)) |

All tools are read-only, idempotent and closed-world (`readOnlyHint`, `idempotentHint`, `openWorldHint:
false` in their configs), and none writes anything.

---

## Architecture

```
 MCP / REST / Ask SAJHA call  qlrisk_value_at_risk
        │
        ▼
 SAJHA tool path (access, policy, approval, validation, cache, audit), in a worker thread
        │
        ▼
 QlriskValueAtRiskTool (sajha/tools/impl/qlrisk/qlrisk_tools.py)  ──►  qlrisk (same process)
```

| File | Role |
|------|------|
| `config/tools/qlrisk/qlrisk_<tool>.json` | One config per tool: name, implementation class, title, description, `requires`, annotations, metadata (no `inputSchema`); the `qlrisk_price_<product>` configs are generated |
| `sajha/tools/impl/qlrisk/generate.py` | The generator of the per-product pricing tool configs |
| `sajha/tools/impl/qlrisk/qlrisk_tools.py` | One class per tool (`QlriskPriceTradesTool`, ...) on the base `QlriskTool`: builds the input schema when the tool loads, runs the handler, shapes the result |
| `sajha/tools/impl/qlrisk/introspect.py` | Reads products, product terms, calculator inputs and configuration, enumerations, stress scenarios and processes from the installed qlrisk |
| `sajha/tools/impl/qlrisk/inputs.py` | Market data, shocks, trades and histories: schemas and parsers |
| `sajha/tools/impl/qlrisk/tools/` | The handlers and schemas, one module per area (`discovery`, `pricing`, `market_risk`, `regulatory`, `counterparty`, `engine`, and `products` for the per-product pricing tools) |
| `sajha/tools/impl/qlrisk/options.py` | The work bounds ([Limits](#limits)) |
| `requirements-qlrisk.txt` | The optional install: the qlrisk wheel (a path to fill in) and QuantLib, numpy and scipy ranges compatible with `requirements.txt` |
| `tests/tools/test_qlrisk_tools.py` | Every tool and mode against the real qlrisk, and calls through `/api/tools/execute` and `/mcp` (skipped without qlrisk) |

Design choices:

- **In process, optional.** The configs declare `"requires": ["qlrisk"]`. Without qlrisk the registry
  skips the tools quietly (they are not failed tools and are absent from `tools/list`) and raises one
  info notice, `tools.requires:qlrisk`, that counts them. The mechanism is generic
  ([Architecture](../../architecture/Architecture.md#tool-config-files-and-folders), "Optional
  dependencies").
- **Schemas from qlrisk.** Each tool's input schema is computed when the tool loads, from the installed
  qlrisk: product names, currencies, risk classes, shock types, stress scenarios, processes, calculator
  input fields and configuration enums, so upgrading qlrisk updates the schemas. Product terms that qlrisk
  takes as keyword arguments are found in the source of each product's pricer. The JSON configs hold only
  the descriptive parts.
- **Validated input, clear errors.** SAJHA checks every call against the schema; the handler then parses
  it and reports anything else wrong with a message naming the field and what to send (for example
  `trades[0] (InterestRateSwap): missing ['maturity_date', 'fixed_rate'] (or tenor_years)`). Both are
  invalid-argument errors: `-32602` on MCP 2026-07-28, `isError: true` on 2025-11-25, HTTP 400 on REST. A
  failure inside qlrisk on valid input is a tool execution error naming the qlrisk exception.
- **Results.** The tool returns the full result object. An MCP caller gets it as `structuredContent`, with
  a text block holding a one-line summary, a newline and the same JSON (cut at `max_text_chars`; the
  structured result is never cut). REST callers get the object as `result`.
- **Off the event loop.** qlrisk is synchronous and CPU-bound; SAJHA runs tool calls in a worker thread on
  `/mcp` and on `POST /api/tools/execute`.

---

## Setup

### 1. Install qlrisk into SAJHA's environment

qlrisk is proprietary and is not on PyPI. Put the path of your qlrisk wheel in `requirements-qlrisk.txt`
(it replaces `/path/to/qlrisk-2.3.1-py3-none-any.whl`) and install it into the environment SAJHA runs in:

```bash
pip install -r requirements-qlrisk.txt
# or directly:  pip install /path/to/qlrisk-<version>-py3-none-any.whl
# with uv:      uv pip install --python <sajha-venv>/bin/python /path/to/qlrisk-<version>-py3-none-any.whl
```

The wheel brings QuantLib, numpy and scipy; the file's ranges keep them compatible with SAJHA's own
requirements. Check it: `python -c "import qlrisk; print(qlrisk.__version__)"`.

### 2. The tools appear

Nothing to configure. The configs are already in `config/tools/qlrisk/` and declare
`"requires": ["qlrisk"]`:

- **qlrisk installed before start-up:** the tools load with the others and are on the Tools page and in
  `tools/list`.
- **qlrisk installed while SAJHA runs:** the registry's retry loop re-checks skipped tools every
  `tools.retry_failed_seconds` (default 300), so the tools load within one interval, without a restart,
  and the notice clears.
- **qlrisk not installed:** the tools are skipped and the info notice `tools.requires:qlrisk` says how
  many are waiting ("qlrisk is not installed: N qlrisk tools are skipped", N counted from the configs). Nothing else is
  reported; the rest of SAJHA is unaffected.

Like any tool, each can be disabled on the Tools page, restricted by role, or given policies
([Policy and Audit](../../architecture/Policy%20and%20Audit.md)).

---

## Common inputs

Most tools take a book (`trades`), `market_data`, `reporting_currency`, and, for VaR-like measures, a
`history`.

### trades

A list of objects, each with `product` (a qlrisk product class, e.g. `InterestRateSwap`, `CorporateBond`,
`CreditDefaultSwap`, `FXOption`, `EquityOption`, `CommodityForward`; `qlrisk_catalog` with topic `products` lists
them all) and the product's terms. Defaults: `trade_id` `<product>-<n>`, `trade_date` and `effective_date`
the valuation date, `currency` `USD`, `counterparty_id` `CP-1`, `netting_set_id` the counterparty.
`tenor_years` can stand in for `maturity_date`. Dates are `YYYY-MM-DD`; enumerations accept qlrisk's value
or name.

```json
{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5,
 "fixed_rate": 0.044, "counterparty_id": "BANK-A"}
{"product": "CorporateBond", "notional": 5000000, "tenor_years": 5, "coupon": 0.05, "issuer": "ACME"}
{"product": "EquityOption", "notional": 1000000, "tenor_years": 0.5, "ticker": "SPX", "strike": 5000, "is_call": false}
{"product": "FXOption", "notional": 2000000, "tenor_years": 1, "pair": "EURUSD", "strike": 1.10, "currency": "EUR"}
```

A term the product's pricer does not read is passed through with a warning in the result's `warnings`.

### market_data

Omit it for qlrisk's sample snapshot valued today. With `base: "sample"` (the default) anything you send
overlays the sample; `base: "empty"` uses only what you send. Fields (read from qlrisk's `MarketData`):
`valuation_date`, `discount_curve`, `forward_curves`, `fx_spots`, `volatility_surfaces`, `credit_curves`,
`dividend_curves`, `equity_prices`, `bond_prices`, `reference_rates`, `commodity_prices`,
`correlation_matrix`. Curves are tenor → value with tenor keys in years (`"5"`) or labels (`"6M"`,
`"5Y"`). `shocks` applies [shocks](#shocks) after the overlay, for a what-if market.

```json
{"valuation_date": "2026-10-09", "forward_curves": {"SOFR": {"1Y": 0.05, "10Y": 0.045}}, "equity_prices": {"SPX": 5100}}
```

`qlrisk_catalog` with topic `market_data` returns the snapshot and every risk-factor key (`EQ.SPX`, `FX.EURUSD`,
`IR.FWD.SOFR.5Y`, `CR.ACME.5Y`, `VOL.eq_vol.1Y`, ...).

### shocks

One factor: `{"factor": "EQ.SPX", "size": -0.2, "shock_type": "relative"}` (`shock_type`: `absolute`,
`relative`, `log`; rates and spreads in decimals, so `0.0025` is 25bp). A curve shape:
`{"curve_field": "forward_curves", "curve_name": "SOFR", "shape": "twist", "short_end": -0.0025, "long_end": 0.0025}`,
`shape` `parallel` (`size`), `twist` (`short_end`, `long_end`) or `butterfly` (`wings`, `belly`); or
`"risk_classes": ["IR"]` to shape every tenored curve of a risk class.

### history

Omit it for qlrisk's synthetic history: correlated, fat-tailed, 750 business days ending at the market
data, with a 60-day stress regime from row 300. Override `seed`, `num_days`, `stress_start`, `stress_days`;
or send `{"source": "supplied", "dates": [...], "factors": ["EQ.SPX", ...], "values": [[...], ...]}`
(levels, one row per date, oldest first).

---

## Tools

Examples were run on the sample market data valued 2026-10-09 (`"market_data": {"valuation_date":
"2026-10-09"}`, left out below for brevity). Figures depend on the market data and the history.

### qlrisk_catalog

**Purpose:** discover what qlrisk can do before calling another tool.

**Inputs:** `topic` (required): `products`, `calculators`, `stress_scenarios`, `report_measures`,
`processes`, `market_data`, `enumerations`, `version`; `name` (a product, a calculator measure or an
enumeration); `category` (products only, e.g. `fx`); `market_data` (for topic `market_data`).

**Outputs:** products: `count`, `categories`, `products` (`name`, `pricing_tool`, `category`, `asset_class`,
`product_type`, `description`, `required`, `terms`); with `name`: `product` (parameters, terms, pricer) and
`trade_schema`. calculators: `calculators` (`measure`, `calculator_type`, `inputs`, `required`, `config`)
and `tool_for_measure` (each measure's tool); with `name`: the full `input_schema` and `config`. version:
`qlrisk_version` and `bounds`.

```json
{"topic": "products", "name": "CorporateBond"}
```

### qlrisk_price_trades

**Purpose:** what trades are worth.

**Inputs:** `trades` (required), `market_data`, `reporting_currency` (default `USD`),
`include_cash_flows` (default false).

**Outputs:** `valuation_date`, `reporting_currency`, `total_npv`, `trades` (`trade_id`, `product`, `npv`,
`currency`, `npv_reporting`, `components`, `greeks`, `risk_measures`, `cash_flows`), `errors`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044}]}
```

```text
1 trade(s) priced on 2026-10-09: total NPV -22,834.98 USD
{"trade_id": "IRS-5Y", "npv": -22834.98, "components": {"fixed_leg_pv": 1960276.75, "float_leg_pv": 1937441.77,
 "annuity": 44551744.33, "par_rate": 0.0434875}, "greeks": {"dv01": 4455.17}, ...}
```

### qlrisk_sensitivities

**Purpose:** what moves the book: bump-and-reprice DV01 (per 1bp), CS01, DIV01, delta, vega, gamma
(central bumps), 1-day theta, key-rate ladders and cross-gamma.

**Inputs:** `trades` (required), `market_data`, `reporting_currency`, `risk_classes` (`IR`, `CR`, `EQ`,
`CM`, `FX`, `OT`), `factors`, `include_theta` (true), `include_ladders` (true), `ladder_vertices`
(`native`, `frtb_girr`, `frtb_csr`, `standard`), `bump_method` (`central`, `forward`),
`cross_gamma_factors` (2 or more factor keys).

**Outputs:** `base_pv`, `by_risk_class` (`risk_class`, `measure`, `value`), `gamma_by_risk_class`,
`by_trade`, `theta`, `by_factor`, `ladders` (`field`, `name`, `measure`, `buckets`), `cross_gamma`,
`errors`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044}],
 "ladder_vertices": "frtb_girr"}
```

```text
Sensitivities in USD for 1 trade(s): DV01 4,561.84
by_risk_class [{"risk_class": "IR", "measure": "dv01", "value": 4561.84}]; theta {"IRS-5Y": 925.36}
ladders: forward_curves/SOFR dv01 {"2.0": 78.28, "3.0": 183.89, "5.0": 4217.99, ...}
```

### qlrisk_value_at_risk

**Purpose:** market-risk VaR and Expected Shortfall.

**Inputs:** `trades`, `market_data`, `reporting_currency`, `history`; `mode` (`portfolio`, or
`pnl_series` with `pnl` and optional `weights`); `method` (`historical`, `age_weighted`,
`filtered_historical`, `monte_carlo`, `parametric`); `confidence` (0.99), `es_confidence` (0.975),
`horizon_days` (1), `lookback` (250), `revaluation` (`full`, `taylor`), `age_decay` (0.98),
`ewma_lambda`, `mc_paths` (5000), `mc_distribution` (`normal`, `student_t`), `mc_dof` (5), `seed` (7),
`decomposition` (true), `group_by` (trade id → group), `include_stressed_var`, `stress_window` (250),
`svar_horizon_days` (10), `liquidity` (`spreads`: trade id → proportional spread; `horizon_days`).

**Outputs:** `var` and `es` (`measure`, `value` as a positive loss, `confidence`, `horizon_days`,
`method`, `n_scenarios`, `contributions`, `tail_scenarios`), `decomposition` (`component`, `incremental`,
`standalone`, `by_group`), `stressed_var`, `liquidity` (`liquidation_cost`, `liquidity_adjusted_var`);
in `pnl_series` mode `var`, `es`, `var_1d`, `es_1d`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044},
            {"product": "EquityOption", "trade_id": "SPX-P", "notional": 1000000, "tenor_years": 0.5, "ticker": "SPX", "strike": 5000, "is_call": false}],
 "method": "historical", "horizon_days": 10, "include_stressed_var": true}
```

```text
historical VaR 99.0% 10d 204,168.67 USD; ES 97.5% 193,300.83; SVaR 561,506.31
var.contributions {"IRS-5Y": 186413.37, "SPX-P": 17755.30}
```

### qlrisk_backtest

**Purpose:** validate a risk model.

**Inputs:** `mode`: `portfolio` (the book's historical VaR and ES over `test_days` (250) after `lookback`
(250), plus PLA; `include_series` returns the daily `hpl`, `rtpl`, `var`, `es`), `var_series` (`pnl`,
`var_forecasts`, `labels`), `es_series` (`pnl`, `var_forecasts`, `es_forecasts`), `pla` (`hpl`, `rtpl`);
`confidence`, `es_confidence`. Forecasts are positive losses.

**Outputs:** `var` (`n`, `exceptions`, `expected_exceptions`, `exception_labels`, `kupiec_lr`,
`kupiec_p_value`, `independence_lr`, `independence_p_value`, `christoffersen_lr`,
`christoffersen_p_value`, `zone`, `multiplier`), `es` (`exceptions`, `z1`, `z2`, `zone`), `pla`
(`spearman`, `ks_statistic`, `zone`, `n`).

```json
{"trades": [...the two trades above...]}
```

```text
Backtest over 250 days: 1 VaR exceptions (green, multiplier 3.0); ES green; PLA green
```

### qlrisk_pnl_explain

**Purpose:** explain the P&L between two market states.

**Inputs:** `trades` (required), `market_data` (the start), and the end: `end_market_data`, or
`end_shocks` and/or `end_valuation_date` (the time roll).

**Outputs:** `start`, `end`, `total` (`actual`, `theta`, `unexplained` and one entry per risk class),
`trades` (`actual`, `theta`, `by_risk_class`, `unexplained`, `top_factors`).

```json
{"trades": [{"product": "EquityOption", "trade_id": "SPX-P", "notional": 1000000, "tenor_years": 0.5, "ticker": "SPX", "strike": 5000, "is_call": false}],
 "end_shocks": [{"factor": "EQ.SPX", "size": -0.05, "shock_type": "relative"}], "end_valuation_date": "2026-10-12"}
```

```text
P&L 2026-10-09 -> 2026-10-12: actual 20,097.86 USD, theta -261.57, unexplained 215.70
```

### qlrisk_stress_test

**Purpose:** stress a book.

**Inputs:** `trades` (required), `market_data`, `reporting_currency`; `mode`: `library` (qlrisk's
historical crises, all or `scenarios`: `1987_black_monday`, `1998_ltcm_russia`, `2008_gfc_lehman`,
`2010_euro_crisis`, `2013_taper_tantrum`, `2016_brexit`, `2020_covid`, `2022_rates_shock`,
`2023_regional_banks` in qlrisk today; the schema reads them from qlrisk), `custom` (`custom_scenarios`:
`{name, shocks}` or `{name, definition}` with `equity`, `vol`, `rates`, `credit`, `fx_usd`, `commodity`,
`fx`), `reverse` (`target_loss`, `history`, `lookback`, `top_n`).

**Outputs:** `base_pv`, `results` worst first (`scenario`, `pnl`, `by_trade`, `description`), `worst`;
reverse: `target_loss`, `achieved_loss`, `scale`, `sigma_distance`, `top_moves`, `shocks`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044}],
 "mode": "custom", "custom_scenarios": [{"name": "rates +100bp", "shocks": [{"risk_classes": ["IR"], "shape": "parallel", "size": 0.01}]}]}
```

```text
1 stress scenario(s); worst rates +100bp P&L 445,355.39 USD
```

With the swap and the SPX put and no `mode`, the library's worst is `2008_gfc_lehman` (-423,225.11 USD); a
reverse stress to a 500,000 loss finds a move 19.04 sigma away.

### qlrisk_frtb_sa_capital

**Purpose:** FRTB Standardised Approach capital (MAR21-23).

**Inputs:** `mode`: `portfolio` (default) with `trades`, `market_data`, `reporting_currency`,
`curve_currency`, `credit_buckets`, `equity_buckets`, `commodity_buckets`, `vol_underlyings`, `ratings`,
`seniority`, `exotic`, `other_residual`, `csr_sector_gamma`, `include_curvature`;
`sbm_from_sensitivities` with `frtb_sensitivities` (`risk_class`, `risk_type`, `bucket`, `name`, `tenor`,
`sensitivity`, `risk_weight`); `drc_from_positions` with `drc_positions` (`obligor`, `rating`,
`notional`, `market_value`, `maturity`, `seniority`, `bucket`, `trade_id`).

**Outputs:** `total`, `summary` (per component, `SBM`, `DRC`, `RRAO`, `TOTAL`), `sbm` (`total`,
`scenario`, `by_scenario`, `by_component`, `by_bucket`, `skipped_factors`), `drc` (`total`, `by_bucket`,
`net_jtd`, `hbr`), `rrao`.

```json
{"trades": [...the swap and the SPX put...], "equity_buckets": {"SPX": 12}, "vol_underlyings": {"eq_vol": "SPX"}}
```

```text
FRTB SA capital 480,976.01 USD: SBM 480,976.01, DRC 0.00, RRAO 0.00; unmapped factors ['DIV.SPX.1Y', 'DIV.SPX.5Y']
```

### qlrisk_frtb_ima_capital

**Purpose:** FRTB Internal Models Approach (MAR31/33).

**Inputs:** `mode`: `full` (default: IMCC, SES for `nmrf`, IMA DRC from `ratings`, capital), `imcc`,
`lh_es`, `liquidity_horizons` (`small_caps`, `high_yield`), `rfet` (`as_of`, `observations`: factor →
dates of real prices), `ima_drc` (`drc_positions`, `n_sims`, `global_correlation`, `sector_correlation`,
`sectors`, `drc_confidence`, `seed`), `capital` (`imcc`, `ses`, `drc`, `multiplier`, `imcc_avg60`,
`ses_avg60`). Book modes take `trades`, `market_data`, `history`, `current_window`, `stress_window`,
`rho`, `revaluation`, `reduced_set`, `liquidity_horizons` (factor → 10/20/40/60/120), `idiosyncratic`,
`seniority`, `multiplier`, `es_confidence`.

**Outputs:** `imcc` (`imcc`, `es_unconstrained`, `es_by_class`, `stress_window`, `ratio`, `details`),
`ses` (`ses`, `by_factor`), `drc` (`drc`, ...), `capital`; `lh_es`: `es`, `components`; `rfet`:
`modellable`, `non_modellable`; `liquidity_horizons`: factor → horizon.

```json
{"mode": "capital", "imcc": 1000000, "ses": 200000, "drc": 100000}
```

```text
IMA capital 1,800,000.00
```

### qlrisk_basel25_capital

**Purpose:** Basel 2.5 capital = max(VaR, m × avg60 VaR) + max(SVaR, m × avg60 SVaR).

**Inputs:** `var_series`, `svar_series`, `exceptions`; or `trades` (with `market_data`, `history`) to
compute 10-day VaR, SVaR and the exception count (needs at least 520 days of history).

**Outputs:** `result` (`capital`, `var_term`, `svar_term`, `multiplier`); with trades also `var_10d`,
`svar_10d`, `exceptions`.

```json
{"var_series": [1000000], "svar_series": [2000000], "exceptions": 3}
```

```text
Basel 2.5 capital 9,000,000.00     (var_term 3,000,000, svar_term 6,000,000, multiplier 3.0)
```

### qlrisk_ccr_exposure

**Purpose:** counterparty exposure.

**Inputs:** `mode`: `trade_profiles` (default without `measure`: each trade's simulated profile; `trades`,
`market_data`, `time_horizon` (5), `num_scenarios` (2000), `confidence_level` (0.95)); `calculator`
(`measure`: `ce`, `ee`, `eee`, `pfe`, `peak`, `stressed`; `inputs` and `config` as the calculator defines
them, listed by `qlrisk_catalog` topic `calculators`); `wrong_way` (`credit_factor` such as `CR.GLOBEX.5Y`,
`history`, `shock_sigmas` (3), `horizon_days` (10), `lookback`, `top_n`).

**Outputs:** profiles: `trades` (`time_grid`, `expected_exposure`, `potential_future_exposure`,
`effective_ee`, `peak_exposure`, `epe`, `effective_epe`, `cva`); calculator: `measure`, `result` (the
calculator's result), `headline`; wrong-way: `base_exposure`, `conditional_exposure`, `ratio`,
`spread_move`, `top_moves`.

```json
{"mode": "calculator", "measure": "pfe", "inputs": {"current_mtm": 100000, "notional": 10000000, "remaining_maturity": 5, "volatility": 0.01}}
```

```text
PFE: 212,925.17
```

### qlrisk_saccr

**Purpose:** SA-CCR exposure at default.

**Inputs:** `mode`: `netting_sets` (default; `trades`, `market_data`, `reporting_currency`, `csa`: netting
set → `margined`, `collateral`, `threshold`, `minimum_transfer_amount`, `nica`, `mpor_days`;
`index_names`), `trades` (stand-alone per trade), `calculator` (`calculator_input`: `netting_set_id`,
`trades` as `{asset_class, notional, maturity, mtm, ...}`, `collateral`, `variation_margin`, `threshold`,
`minimum_transfer_amount`, `margin_period_of_risk`, `is_margined`).

**Outputs:** `netting_sets` (`netting_set`, `mtm`, `collateral`, `replacement_cost`, `addon_by_class`,
`addon`, `multiplier`, `ead`, `trades`), `ead_total`; trades: per trade `replacement_cost`,
`pfe_add_on`, `ead`, `asset_class`, `hedging_set_contributions`, and `ead_sum`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044, "counterparty_id": "BANK-A"}],
 "csa": {"BANK-A": {"margined": true, "threshold": 0}}}
```

```text
SA-CCR EAD 78,272.06 USD across 1 netting set(s)     (BANK-A: RC 0, add-on 66,351.77, multiplier 0.843)
```

### qlrisk_initial_margin

**Purpose:** initial margin.

**Inputs:** `positions` (required; `notional`, `product_type`, `remaining_maturity`, `volatility`,
`delta`, `delta_sensitivities`, `vega_sensitivities`, `curvature_sensitivities`, `correlation_within`,
`correlation_across`, `margin_period_of_risk`, `gross_notional`, `net_to_gross_ratio`), `method` (`simm`
by default, `schedule`, `var`), `confidence_level`, `mpor_scaling`. One position gives its IM; several
give the portfolio IM.

**Outputs:** `result` (`initial_margin`, `im_as_pct_notional`, `method`, `components`), `headline`.

```json
{"method": "simm", "positions": [{"notional": 10000000, "product_type": "irs", "remaining_maturity": 5, "delta_sensitivities": {"USD-5Y": 4500}}]}
```

```text
Initial margin (simm): 450.00
```

### qlrisk_credit_risk

**Purpose:** credit-risk measures.

**Inputs:** `measure` (`pd`, `lgd`, `ead`, `el`, `economic_capital`, `raroc`), `inputs`, `config`. The
fields and configuration of each come from the qlrisk calculator and are in the tool description and in
`qlrisk_catalog` topic `calculators`; for example `pd` takes `credit_rating`, or `asset_value`, `debt_value`,
`asset_volatility`, `risk_free_rate`, or `hazard_rate`, with `config.model` one of `structural`,
`reduced_form`, `transition_matrix`, `logistic`, `historical`.

**Outputs:** `measure`, `result`, `headline` (PD and LGD are the result itself; others the main field,
e.g. `expected_loss`, `economic_capital`, `raroc`).

```json
{"measure": "pd", "inputs": {"credit_rating": "BBB"}, "config": {"model": "transition_matrix"}}
```

```text
PD: 0.004
```

`{"measure": "el", "inputs": {"pd": 0.02, "lgd": 0.45, "ead": 1000000}}` gives `EL: 9,000.00`.

### qlrisk_xva

**Purpose:** valuation adjustments and CVA capital.

**Inputs:** `measure`: `cva`, `dva`, `fva`, `kva`, `mva` (`inputs`, `config` from the qlrisk calculator;
e.g. `cva`: `ee_profile`, `time_grid`, `credit_spread`, `recovery_rate`, ...); `total` (`inputs`: one
object per adjustment plus `colva` as a number); `sa_cva` (`counterparty` (a credit curve in the market
data), `time_grid`, `expected_exposure`, `recovery`, `counterparty_buckets`: name → [MAR50 bucket,
investment grade], `hedges` (trades), `m_cva`, `reference_buckets`, `market_data`, `reporting_currency`);
`ba_cva` (`counterparties`: `name`, `sector`, `investment_grade`, `netting_sets` as [EAD, maturity],
`hedges`; `index_hedges`).

**Outputs:** calculators: `result`, `headline`; total: `components` (`cva`, `dva`, `fva`, `kva`, `mva`,
`colva`, `total_xva`), `details`, `convention`; sa_cva: `cva`, `capital`, `by_component`, `by_bucket`;
ba_cva: `result` (`k_reduced`, `capital_reduced`, `scva`, `capital`, ...).

```json
{"measure": "cva", "inputs": {"ee_profile": [2e6, 3e6, 3.5e6, 3e6, 2e6, 1e6], "time_grid": [0.5, 1, 2, 3, 4, 5], "credit_spread": 0.012}}
```

```text
CVA: 118,737.19
```

The same profile as SA-CVA on ACME (`"counterparty_buckets": {"ACME": ["3", true]}`): CVA 115,136.81 and
capital 294,291.64 USD. BA-CVA for one investment-grade financial with a 10m, 5-year netting set:
1,026,996.36.

### qlrisk_simulate_paths

**Purpose:** Monte Carlo paths of qlrisk's processes (`gbm`, `ou`, `cir`, `heston`, `vasicek`,
`hull_white`, `merton_jump` in qlrisk today; the enum lists only those the generator supports).

**Inputs:** `process`, `initial_value` (required), `drift`, `volatility`, `maturity`, `num_steps`,
`num_paths`, `mean_reversion_speed`, `long_term_mean`, `vol_of_vol`, `correlation`, `initial_variance`,
`jump_intensity`, `jump_mean`, `jump_std`, `seed` (7), `percentiles` ([5, 50, 95]), `sample_paths` (3,
at most 10).

**Outputs:** `time_grid` (at most 60 points), `mean`, `std`, `percentiles`, `terminal` (`mean`, `std`,
`min`, `max`, percentiles), `sample_paths`, `parameters`, `metadata`. The full path matrix is never
returned.

```json
{"process": "gbm", "initial_value": 100, "drift": 0.05, "volatility": 0.2, "maturity": 1, "num_steps": 252, "num_paths": 10000}
```

```text
10000 gbm paths x 252 steps: terminal mean 105.157, std 21.382
```

### qlrisk_risk_report

**Purpose:** every risk in one call with qlrisk's `RiskEngine`.

**Inputs:** `trades`, `market_data`, `history`, `reporting_currency`, or `use_demo_book: true` (qlrisk's
demo book: swap, bond, CDS, FX option, equity option, commodity forward, with its history, hierarchy and
FRTB maps); `measures` (`PV`, `SENSITIVITIES`, `VAR`, `ES`, `PARAMETRIC_VAR`, `SVAR`, `STRESS`,
`BACKTEST`, `FRTB_SA`, `EXPOSURE`; the default is qlrisk's default set), `confidence`, `es_confidence`,
`lookback`, `horizon_days` (10), `stress_window`, `hierarchy` (`levels`, `paths`: trade id → path),
`limits`, `frtb` (as in `frtb_sa_capital`), `csa`.

**Outputs:** `as_of`, `currency`, `metrics` (`pv.total`, `var.1d`, `var.10d`, `es.1d`, `svar.10d`,
`frtb_sa.*`, `stress.worst`, `exposure.*`, `<measure>.<risk class>` ...), `by_node`, `notes`,
`measures`, `trades`, `limits`, `stress`, `netting_sets`.

```json
{"use_demo_book": true, "limits": [{"name": "Firm 1d VaR", "metric": "var.1d", "limit": 500000}]}
```

The demo book values itself today, so its date and figures move:

```text
Risk report 2026-10-10 in USD: pv.total 11,390,256.04, var.1d 329,796.11, es.1d 339,983.10, svar.10d 2,761,917.56,
frtb_sa.total 7,061,106.43, exposure.saccr_ead_netted 19,633,215.16
limits: Firm 1d VaR utilisation 0.66, green
```

### qlrisk_check_limits

**Purpose:** limit monitoring for figures you already have.

**Inputs:** `limits` (required; `name`, `metric`, `limit`, `node` (`ALL`), `amber` (0.75), `red` (0.9),
`absolute`), `metrics` (headline metric → value), `by_node` (node → metric → value), `currency`.

**Outputs:** `checks` (`name`, `node`, `metric`, `value`, `limit`, `utilisation`, `status`: `green`,
`amber`, `red`, `breach`), `breaches`, `counts`.

```json
{"metrics": {"var.1d": 420000}, "limits": [{"name": "Firm VaR", "metric": "var.1d", "limit": 500000}]}
```

```text
1 limit(s) checked: 1 amber      (utilisation 0.84)
```

---

## Per-product pricing tools

Besides `qlrisk_price_trades` (any mix of products in one book), there is one pricing tool per qlrisk
product, named `qlrisk_price_<product>`: the product class in snake case, for example
`qlrisk_price_corporate_bond`, `qlrisk_price_interest_rate_swap`, `qlrisk_price_fx_option`. Each one's
input schema holds **only that product's fields**: its constructor parameters and the keyword terms its
pricer reads (types, enums and defaults from qlrisk), `tenor_years` where the product has a maturity, and
the same `market_data`, `reporting_currency` and `include_cash_flows` as `qlrisk_price_trades`. A field the
product does not have is rejected. The description names the required fields and the pricer terms and
carries an example. The result is the trade's row of `qlrisk_price_trades` with `valuation_date` and
`reporting_currency`: `npv` and `currency`, `npv_reporting`, `components`, `greeks`, `risk_measures`, and
`cash_flows` when asked.

**Finding them.** They are in the `qlrisk` folder of the Tools page with the other qlrisk tools, and in
`tools/list`; `qlrisk_catalog` with topic `products` lists every product with its `pricing_tool`.

**Generated, not written.** The configs (`config/tools/qlrisk/qlrisk_price_*.json`, all with the one
implementation `QlriskPriceProductTool` and the product in their `"product"` key) are written by a
generator that reads qlrisk's product registry:

```bash
python -m sajha.tools.impl.qlrisk.generate            # write the configs; remove those of products that are gone
python -m sajha.tools.impl.qlrisk.generate --check    # report differences, write nothing (exit 1 if any)
```

For each product it builds a small example trade, checks it against the tool's schema and prices it on the
sample market (valued 2026-10-09, so the output is stable). A product that cannot be priced standalone is
skipped and printed with the reason. `tests/tools/test_qlrisk_tools.py` fails when the files differ from
what the generator would write now, so a qlrisk upgrade that adds, removes or changes products is caught:
run the generator and commit the result. As with every qlrisk tool, the input schema itself is built from
the installed qlrisk when the tool loads.

**Example.** A 5-year fixed-rate corporate bond and a 5-year payer swap (on `"market_data":
{"valuation_date": "2026-10-09"}`):

```json
qlrisk_price_corporate_bond     {"notional": 5000000, "tenor_years": 5, "coupon": 0.05, "issuer": "ACME"}
qlrisk_price_interest_rate_swap {"notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044}
```

```text
CorporateBond CorporateBond-1 on 2026-10-09: NPV 4,886,813.03 USD
  components {"maturity": 4.9993, "credit_spread": 0.0120}
InterestRateSwap InterestRateSwap-1 on 2026-10-09: NPV -22,834.98 USD
  components {"fixed_leg_pv": 1960276.75, "float_leg_pv": 1937441.77, "annuity": 44551744.33, "par_rate": 0.04349}
  greeks {"dv01": 4455.17}
```

The swap tool requires `notional` and `fixed_rate` (plus `maturity_date` or `tenor_years`) and offers
`floating_index`, `is_payer`, frequencies, day counts, `spread` and `amortization_schedule`; the bond tool
requires only `notional` and the maturity and offers `coupon`, `frequency`, `issuer` (its credit curve) and
`is_long`.

---

## Calling the Tools

Like any SAJHA tool: MCP `tools/call`, REST, Ask SAJHA, composites and workflows.

```bash
curl -s -X POST http://localhost:3002/api/tools/execute -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -d '{"tool": "qlrisk_price_trades", "arguments": {"trades": [{"product": "InterestRateSwap", "notional": 10000000, "tenor_years": 5, "fixed_rate": 0.044}]}}'
```

REST returns the result object as `result`; MCP returns it as `structuredContent` with the summary line and
the JSON in the text block. Ask SAJHA picks the tools from their descriptions, which say when to use each
and carry a small example; [Tutorial 41](../../tutorials/TUTORIAL_41_qlrisk_risk_tools.md) walks through all of
this.

---

## Limits

Each bound is the configuration key `qlrisk.<bound>` (environment variable `SAJHA_QLRISK_<BOUND>`), read
when a tool loads; a tool config may override bounds for that one tool with a `"bounds"` object, for
example `"bounds": {"max_mc_paths": 5000}` in `qlrisk_ccr_exposure.json`. A request above a bound is
rejected with a message naming it, never cut silently; bounds that limit an input also appear in the input
schema (`maxItems`, `maximum`). `qlrisk_catalog` topic `version` returns the bounds in force.

| Bound | Key | Default |
|---|---|---|
| Trades per request | `qlrisk.max_trades` | 200 |
| Monte Carlo paths, scenarios and calculator simulations | `qlrisk.max_mc_paths` | 20000 |
| Time steps of a simulated path | `qlrisk.max_time_steps` | 1000 |
| Days of history (synthetic or supplied) | `qlrisk.max_history_days` | 2500 |
| IMA DRC simulations | `qlrisk.max_drc_simulations` | 200000 |
| Cross-gamma factors | `qlrisk.max_cross_gamma_factors` | 8 |
| Characters of JSON in the MCP text block | `qlrisk.max_text_chars` | 20000 |

The keys are also in the [Configuration Reference](../../getting-started/Configuration%20Reference.md#qlrisk).

Other limits:

- The defaults (sample market data, synthetic history) are for exploration; production numbers need your
  market data and history, sent in `market_data` and `history` on each call. The tools keep no state
  between calls.
- The results are qlrisk's: its models, conventions and simplifications (for FRTB, securitisation and
  inflation factors are not modelled) are documented with qlrisk.
- Calculators run qlrisk's Python implementations; qlrisk falls back to them where its QuantLib
  implementations are incomplete.
- A call runs in one of SAJHA's worker threads until it finishes; a large book, many paths or a long
  history holds that thread for seconds to tens of seconds. Keep the bounds sized for your hardware.

---

## What is not wrapped

| qlrisk capability | Why |
|---|---|
| ColVA as a calculation | qlrisk has no ColVA calculator, only a field of its XVA total; `qlrisk_xva` with measure `total` accepts a ColVA figure and adds it |
| `DataGenerator` / `create_test_dataset` (random test trades and counterparties) | Test-data generation, not risk; the synthetic history and the demo book cover exploration |
| Report files (`RiskReport.to_csv`, `to_json(path)`), the `qlrisk` command-line demos | They write files; the tools are read-only and return the report as JSON |
| QuantLib calculator implementations (`ImplementationType.QUANTLIB`) | qlrisk marks most of them incomplete and falls back to Python, so the tools run the Python calculators |
| `MarketRiskEngine` building blocks (`ScenarioSet`, `PnLMatrix`, `taylor_pnl`, `find_stress_window`, `covariance`) | Exposed through the measures that use them (`qlrisk_value_at_risk`, `qlrisk_backtest`, `qlrisk_stress_test`, `qlrisk_frtb_ima_capital`) rather than as separate tools |
| Domain models (`Portfolio`, `Counterparty`, `CollateralAgreement`, `TransitionMatrix`, ...) | Inputs are plain JSON; trades, CSAs and limits cover what the measures need |

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| No `qlrisk_*` tools, and the notice "qlrisk is not installed" | qlrisk is not importable in SAJHA's environment: install the wheel into the python that runs SAJHA ([Setup](#setup)); the tools load within `tools.retry_failed_seconds` |
| qlrisk installed, but the tools stay skipped | It went into another environment (check with that python: `python -c "import qlrisk"`), or `tools.retry_failed_seconds` is `0` (then reload the tools or restart) |
| A tool is in the failed tools with `Failed to load: ...` | qlrisk imports but fails (for example a QuantLib built for another Python); the error names the module. Reinstall QuantLib for SAJHA's Python |
| `... exceeds the bound max_...` or `greater than the maximum of ...` | A [work bound](#limits); lower the request or raise `qlrisk.<bound>` |
| `trades[0] (X): missing [...]` | The product's required fields; `qlrisk_catalog` with topic `products` and `name` shows them |
| `term 'x' is not one qlrisk's pricer reads` in `warnings` | A misspelt or unused term; check `terms` in the catalog |
| `unmapped factors` in FRTB SA | Map the names with `credit_buckets`, `equity_buckets`, `commodity_buckets`, `vol_underlyings`, `curve_currency` |
| `counterparty 'X' has no credit curve` (SA-CVA) | Add `market_data.credit_curves.X` |
| A slow call | Send a smaller book, fewer paths or a shorter history, or lower the bounds |

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
