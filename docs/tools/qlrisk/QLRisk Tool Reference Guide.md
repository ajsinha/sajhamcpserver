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
  `trades[0] (InterestRateSwap): 'maturity' is a required property`). Both are
  invalid-argument errors: `-32602` on MCP 2026-07-28, `isError: true` on 2025-11-25, HTTP 400 on REST. A
  failure inside qlrisk on valid input is a tool execution error naming the qlrisk exception.
- **Results.** The tool returns the full result object. An MCP caller gets it as `structuredContent`, with
  a text block holding a one-line summary, a newline and the same JSON (cut at `max_text_chars`; the
  structured result is never cut). REST callers get the same object as `result`: the REST `result` and the
  MCP `structuredContent` are identical, including `warnings` (values outside the usual range, ignored
  inputs), `qlrisk_inputs` (calculator inputs and configuration, shocks, stylised stresses and liquidity
  spreads exactly as qlrisk received them, keyed by where they were sent) and, for the per-product tools,
  `qlrisk_terms`.
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

**Essentials first.** Each tool's schema lists its essential inputs at the top (for VaR: `trades`,
`method`, `confidence_pct`, `es_confidence_pct`, `horizon_days`) and puts everything else, including
`market_data`, `reporting_currency` and `history`, in one optional `advanced` object; on
`/tools/<name>/execute` that is a collapsed section, and the JSON boxes (`trades` and the like) start
filled with the tool's worked example, so **Execute** runs it as is. The layout (essentials, renamed
fields, worked example) is one table, `sajha/tools/impl/qlrisk/tools/layout.py`; the schema's `examples`
holds the example.

**Units.** The same field means the same unit everywhere, and the name says which: rates, coupons,
probabilities, LGDs, recoveries, haircuts, margins and volatilities in percent (`*_pct`: `coupon_pct` 3 =
3%, `pd_pct` 2 = 2%), spreads and fees in basis points (`*_bp`: `credit_spread_bp` 120 = 1.2%), confidence
levels in percent (`confidence_pct` 99), horizons in days where the name says `_days` and in years where it
says `_years` or the title does (`time_horizon`, `time_grid`). qlrisk itself takes decimals; the tools
convert, and every result shows what qlrisk received (`qlrisk_inputs`, `qlrisk_terms`). Values outside hard
bounds are rejected with the field named (`inputs (el).pd_pct: 200 is outside 0 to 100 percent (it is in
percent: 2 means 2%)`); a qlrisk name that was renamed is refused with the new one (`pd is now pd_pct
(percent)`); plausible but unusual values run with a warning (`pd_pct = 0.02 means 0.02%; for 2% send 2`).
This covers trades, calculator `inputs` and `config` (`credit_risk`, `xva`, `ccr_exposure` calculator
mode), shocks, stylised stresses, liquidity spreads and nested product terms; the full list is
[Units of qlrisk's own objects](#units-of-qlrisks-own-objects). What still takes qlrisk's decimals:
market-data levels you overlay (`market_data` curves and vol surfaces, as `qlrisk_catalog` topic
`market_data` shows them), simulation parameters (`drift`, `volatility`, rate `initial_value` of
`qlrisk_simulate_paths`), `qlrisk_initial_margin` positions, the SA-CCR calculator input, CSA terms, FRTB
sensitivity risk weights and BA-CVA counterparties.

### trades

A list of objects, each with `product` (a qlrisk product class, e.g. `InterestRateSwap`, `CorporateBond`,
`CreditDefaultSwap`, `FXOption`, `EquityOption`, `CommodityForward`; `qlrisk_catalog` with topic `products` lists
them all with their inputs) and **the inputs of that product's `qlrisk_price_<product>` tool, flat and in
the same units** ([Per-product pricing tools](#per-product-pricing-tools)): `maturity` as a tenor or a date,
the amount under the product's name (`face_value`, `notional`, `principal` ...), rates in percent, spreads
in basis points, and the trade fields that tool keeps in `advanced` (`trade_id`, `counterparty_id`,
`issuer`, `position` ...) at the same level, plus `netting_set_id`. Defaults: `trade_id` `<product>-<n>`,
trade and effective dates the valuation date, `currency` `USD`, `counterparty_id` `CP-1`, `netting_set_id`
the counterparty. Each trade is checked against its product's inputs, and an error names the trade and the
field (`trades[0] (InterestRateSwap): Additional properties are not allowed ('fixed_rate' was unexpected);
InterestRateSwap takes [...] (rates in percent ...)`).

```json
{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000,
 "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}
{"product": "CorporateBond", "maturity": "5Y", "face_value": 5000000, "coupon_pct": 5, "issuer": "ACME"}
{"product": "EquityOption", "maturity": "6M", "notional": 1000000, "ticker": "SPX", "strike": 5000, "option_type": "put"}
{"product": "FXOption", "maturity": "1Y", "notional": 2000000, "pair": "EURUSD", "strike": 1.10, "currency": "EUR"}
```

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

The same shape in `market_data.shocks`, `qlrisk_pnl_explain` `end_shocks` and `qlrisk_stress_test` custom
scenarios. `shock_type` is `absolute` (adds the size; the default), `relative` (multiplies by 1 + size) or
`log` (by exp(size)). The size field names its unit, which depends on what the factor is and the shock type:

| Factor (qlrisk kind) | `absolute` | `relative`, `log` |
|---|---|---|
| Rates (`IR.*`), credit spreads (`CR.*`), dividend yields (`DIV.*`) | `size_bp`: basis points added, 25 = +0.25% | `size_pct`: -10 = the level x 0.90 (log: x exp(-0.10)) |
| Volatilities (`VOL.*`) | `size_pct`: vol points added, 5 = 20% -> 25% | `size_pct` |
| Prices (`EQ.*`, `CMDTY.*`, `BOND.*`), FX spots (`FX.*`), other scalars | `size`: the factor's own units, `EQ.SPX` -250 = 250 points down | `size_pct` |

One factor: `{"factor": "EQ.SPX", "shock_type": "relative", "size_pct": -20}`;
`{"factor": "IR.FWD.SOFR.5Y", "size_bp": 25}`. A curve shape takes the same suffix on its sizes:
`{"curve_field": "forward_curves", "curve_name": "SOFR", "shape": "twist", "short_end_bp": -25, "long_end_bp": 25}`,
`shape` `parallel` (`size_*`), `twist` (`short_end_*` at 2y and in, `long_end_*` at 10y and out) or
`butterfly` (`wings_*`, `belly_*` at 5y); or `"risk_classes": ["IR"]` to shape every tenored curve of a risk
class. A curve shock moves the factors its unit fits: `{"risk_classes": ["IR"], "size_bp": 100}` moves every
rate curve by 100bp and leaves the IR volatility surfaces alone (move those with a `size_pct` shock on
`curve_field` `volatility_surfaces`). The wrong field is an error naming the shock and what to send
(`custom_scenarios[0].shocks[0]: a relative shock to a price takes size_pct (percent of the level: -10 means
the level x 0.90), not size`); a relative move below -100%, or beyond +/-5,000bp on a rate, is refused;
moves beyond 50% or 1,000bp, and sizes like `size_bp` 0.01 that look like decimals, run with a warning.

### Units of qlrisk's own objects

Every field the tools rename or convert, from the table in `sajha/tools/impl/qlrisk/generate.py` (`CALC_INPUTS`, `CALC_CONFIG`, `STRESS_DEFINITION`, `LIQUIDITY`, `NESTED_*`; product fields are in [Per-product pricing tools](#per-product-pricing-tools)). "qlrisk receives" is the conversion of the value x you send. Fields not listed (amounts, prices, counts, flags, names, correlations from -1 to 1 or 0 to 1, time grids in years) pass unchanged. Some fields qlrisk declares but its calculator does not read (the PFE calculator's `credit_spread` and `fx_rate`, EL's `maturity`); their descriptions say so.

**Calculators: `qlrisk_credit_risk`** (`inputs` and `config` per measure)

| Field | qlrisk field | Unit | qlrisk receives | Where |
|---|---|---|---|---|
| `asset_volatility_pct` | `asset_volatility` | % | x / 100 | pd |
| `risk_free_rate_pct` | `risk_free_rate` | % | x / 100 | pd |
| `time_horizon_years` | `time_horizon` | years | as is | pd, pd config, el, el config, economic_capital |
| `hazard_rate_pct` | `hazard_rate` | % | x / 100 | pd |
| `rating_pd_pct` | `rating_pd` | % | x / 100 | pd |
| `recovery_pct` | `recovery_rate` | % | x / 100 | lgd, el |
| `haircut_pct` | `haircut` | % | x / 100 | lgd collateral[] |
| `recovery_history_pct` | `recovery_history` | % | x / 100 | lgd |
| `lgd_mean_pct` | `lgd_mean` | % | x / 100 | lgd |
| `lgd_std_pct` | `lgd_std` | % | x / 100 | lgd |
| `default_lgd_pct` | `default_lgd` | % | x / 100 | lgd config |
| `floor_pct` | `floor` | % | x / 100 | lgd config |
| `cap_pct` | `cap` | % | x / 100 | lgd config |
| `credit_conversion_factor_pct` | `credit_conversion_factor` | % | x / 100 | ead |
| `add_on_factor_pct` | `add_on_factor` | % | x / 100 | ead |
| `collateral_haircut_pct` | `collateral_haircut` | % | x / 100 | ead |
| `netting_benefit_pct` | `netting_benefit` | % | x / 100 | ead |
| `margin_period_of_risk_days` | `margin_period_of_risk` | business days | x / 252 (years) | ead |
| `pd_pct` | `pd` | % | x / 100 | el, economic_capital |
| `lgd_pct` | `lgd` | % | x / 100 | el, economic_capital |
| `maturity_years` | `maturity` | years | as is | el |
| `pd_term_structure_pct` | `pd_term_structure` | % | x / 100 | el |
| `pds_pct` | `pds` | % | x / 100 | economic_capital |
| `lgds_pct` | `lgds` | % | x / 100 | economic_capital |
| `confidence_pct` | `confidence_level` | % | x / 100 | economic_capital, economic_capital config |
| `tax_rate_pct` | `tax_rate` | % | x / 100 | raroc |
| `hurdle_rate_pct` | `hurdle_rate` | % | x / 100 | raroc, raroc config |

**Calculators: `qlrisk_ccr_exposure`, mode `calculator`**

| Field | qlrisk field | Unit | qlrisk receives | Where |
|---|---|---|---|---|
| `collateral_haircut_pct` | `collateral_haircut` | % | x / 100 | ce |
| `remaining_maturity_years` | `remaining_maturity` | years | as is | ee, eee, pfe, peak, stressed |
| `volatility_pct` | `volatility` | % | x / 100 | ee, eee, pfe, peak, stressed |
| `margin_period_of_risk_days` | `margin_period_of_risk` | business days | x / 252 (years) | ee, eee, pfe |
| `interest_rate_pct` | `interest_rate` | % | x / 100 | ee, eee, pfe |
| `drift_pct` | `drift` | % | x / 100 | ee, eee |
| `credit_spread_bp` | `credit_spread` | bp | x / 10,000 | pfe |
| `time_horizon_years` | `time_horizon` | years | as is | pfe config |
| `confidence_pct` | `confidence_level` | % | x / 100 | pfe config, peak |
| `rate_shock_bp` | `rate_shock` | bp | as is | stressed |
| `fx_shock_pct` | `fx_shock` | % | x / 100 | stressed |
| `credit_shock_bp` | `credit_shock` | bp | as is | stressed |
| `volatility_shock_pct` | `volatility_shock` | % | 1 + x / 100 | stressed |

**Calculators: `qlrisk_xva`** (`cva` ... `mva`, and each part of `total`)

| Field | qlrisk field | Unit | qlrisk receives | Where |
|---|---|---|---|---|
| `credit_spread_bp` | `credit_spread` | bp | x / 10,000 | cva |
| `recovery_pct` | `recovery_rate` | % | x / 100 | cva |
| `spread_term_structure_bp` | `spread_term_structure` | bp | x / 10,000 | cva |
| `discount_rates_pct` | `discount_rates` | % | x / 100 | cva |
| `risk_free_rate_pct` | `risk_free_rate` | % | x / 100 | cva |
| `own_credit_spread_bp` | `own_credit_spread` | bp | x / 10,000 | cva |
| `own_recovery_pct` | `own_recovery_rate` | % | x / 100 | cva |
| `own_pd_curve_pct` | `own_pd_curve` | % | x / 100 | dva |
| `own_lgd_pct` | `own_lgd` | % | x / 100 | dva |
| `discount_curve_pct` | `discount_curve` | % | x / 100 | dva, fva, kva, mva |
| `funding_spread_bp` | `funding_spread` | bp | x / 10,000 | fva, mva |
| `counterparty_survival_curve_pct` | `counterparty_survival_curve` | % | x / 100 | fva |
| `counterparty_pd_pct` | `counterparty_pd` | % | x / 100 | kva |
| `counterparty_lgd_pct` | `counterparty_lgd` | % | x / 100 | kva |
| `cost_of_capital_pct` | `cost_of_capital` | % | x / 100 | kva |
| `capital_floor_pct` | `capital_floor` | % | x / 100 | kva |

**Stylised stresses and liquidity** (`qlrisk_stress_test` `definition`, `qlrisk_value_at_risk` `liquidity`)

| Field | qlrisk field | Unit | qlrisk receives | Where |
|---|---|---|---|---|
| `equity_pct` | `equity` | % | x / 100 | definition |
| `vol_pct` | `vol` | % | x / 100 | definition |
| `rates_bp` | `rates` | bp | x / 10,000 | definition |
| `credit_pct` | `credit` | % | x / 100 | definition |
| `fx_usd_pct` | `fx_usd` | % | x / 100 | definition |
| `commodity_pct` | `commodity` | % | x / 100 | definition |
| `fx_pct` | `fx` | % | x / 100 | definition |
| `spreads_bp` | `spreads` | bp | x / 10,000 | liquidity |

**Nested product terms** (per-product tools and trades in any tool)

| Field | qlrisk field | Unit | qlrisk receives | Where |
|---|---|---|---|---|
| `haircut_pct` | `haircut` | % | x / 100 | MarginLending collateral_positions, CollateralSwap receive_leg, CollateralSwap deliver_leg, MarginLoan terms.collateral_positions[], PrimeBrokerage terms.positions[], StockLoan terms, TriPartyRepo terms, SecuritiesBorrowing borrowed_securities |
| `concentration_limit_pct` | `concentration_limit` | % | x / 100 | MarginLending collateral_positions, PrimeBrokerage terms |
| `volatility_pct` | `volatility` | % | x / 100 | MarginLending collateral_positions, CollateralSwap receive_leg, CollateralSwap deliver_leg, SecuritiesBorrowing borrowed_securities |
| `coupon_rate_pct` | `coupon_rate` | % | x / 100 | BondTRS terms |
| `spread_over_benchmark_bp` | `spread_over_benchmark` | bp | as is | BondTRS terms |
| `financing_spread_bp` | `financing_spread` | bp | as is | BondTRS terms, EquityTRS terms |
| `recovery_pct` | `recovery_rate` | % | x / 100 | BondTRS terms |
| `dividend_yield_pct` | `dividend_yield` | % | x / 100 | EquityTRS terms, StockLoan terms, SecuritiesBorrowing borrowed_securities |
| `storage_cost_pct` | `storage_cost` | % | x / 100 | CommodityFuture terms |
| `convenience_yield_pct` | `convenience_yield` | % | x / 100 | CommodityFuture terms |
| `interest_spread_bp` | `interest_spread` | bp | as is | MarginLoan terms |
| `initial_margin_pct` | `initial_margin_pct` | % | x / 100 | MarginLoan terms |
| `maintenance_margin_pct` | `maintenance_margin_pct` | % | x / 100 | MarginLoan terms |
| `current_ltv_pct` | `current_ltv` | % | x / 100 | MarginLoan terms |
| `financing_rate_spread_bp` | `financing_rate_spread` | bp | as is | PrimeBrokerage terms |
| `short_rebate_spread_bp` | `short_rebate_spread` | bp | as is | PrimeBrokerage terms |
| `initial_margin_requirement_pct` | `initial_margin_requirement` | % | x / 100 | PrimeBrokerage terms |
| `maintenance_margin_pct` | `maintenance_margin` | % | x / 100 | PrimeBrokerage terms |
| `house_margin_excess_pct` | `house_margin_excess` | % | x / 100 | PrimeBrokerage terms |
| `rehypothecation_limit_pct` | `rehypothecation_limit` | % | x / 100 | PrimeBrokerage terms |
| `custody_fee_bps` | `custody_fee_bps` | bp | as is | PrimeBrokerage terms |
| `execution_fee_bps` | `execution_fee_bps` | bp | as is | PrimeBrokerage terms |
| `collateral_margin_pct` | `collateral_margin` | % | x / 100 | StockLoan terms |
| `rebate_rate_bp` | `rebate_rate` | bp | x / 10,000 | StockLoan terms |
| `lending_fee_bp` | `lending_fee` | bp | x / 10,000 | StockLoan terms |
| `stock_volatility_pct` | `stock_volatility` | % | x / 100 | StockLoan terms |
| `repo_rate_pct` | `repo_rate` | % | x / 100 | TriPartyRepo terms |
| `floating_spread_bp` | `floating_spread` | bp | as is | TriPartyRepo terms |
| `special_rate_pct` | `special_rate` | % | x / 100 | SecuritiesBorrowing borrowed_securities |

Shock sizes are in [shocks](#shocks).

### history

Omit it for qlrisk's synthetic history: correlated, fat-tailed, 750 business days ending at the market
data, with a 60-day stress regime from row 300. Override `seed`, `num_days`, `stress_start`, `stress_days`;
or send `{"source": "supplied", "dates": [...], "factors": ["EQ.SPX", ...], "values": [[...], ...]}`
(levels, one row per date, oldest first).

---

## Tools

Examples were run on the sample market data valued 2026-10-09 (`"advanced": {"market_data":
{"valuation_date": "2026-10-09"}}`, left out below for brevity). Figures depend on the market data and the
history. Each tool's description carries its own worked example with its real result, and a test keeps
those figures true.

### qlrisk_catalog

**Purpose:** discover what qlrisk can do before calling another tool.

**Inputs:** `topic` (required): `products`, `calculators`, `stress_scenarios`, `report_measures`,
`processes`, `market_data`, `enumerations`, `version`; `name` (a product, a calculator measure or an
enumeration); `category` (products only, e.g. `fx`); in `advanced`, `market_data` (for topic `market_data`).

**Outputs:** products: `count`, `categories`, `products` (`name`, `pricing_tool`, `category`, `asset_class`,
`product_type`, `description`, `required`, `inputs`, `trade_fields`); with `name`: `product`, `pricing_tool`
and `trade_schema` (the trade's inputs in the tools' units). calculators: `calculators` (`measure`, `calculator_type`, `inputs`, `required`, `config`)
and `tool_for_measure` (each measure's tool); with `name`: the full `input_schema` and `config`. version:
`qlrisk_version` and `bounds`.

```json
{"topic": "products", "name": "CorporateBond"}
```

### qlrisk_price_trades

**Purpose:** what trades are worth.

**Inputs:** `trades` (required); in `advanced`: `market_data`, `reporting_currency` (default `USD`),
`include_cash_flows` (default false).

**Outputs:** `valuation_date`, `reporting_currency`, `total_npv`, `trades` (`trade_id`, `product`, `npv`,
`currency`, `npv_reporting`, `components`, `greeks`, `risk_measures`, `cash_flows`), `errors`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4}]}
```

```text
1 trade(s) priced on 2026-10-09: total NPV -22,834.98 USD
{"trade_id": "IRS-5Y", "npv": -22834.98, "components": {"fixed_leg_pv": 1960276.75, "float_leg_pv": 1937441.77,
 "annuity": 44551744.33, "par_rate": 0.0434875}, "greeks": {"dv01": 4455.17}, ...}
```

### qlrisk_sensitivities

**Purpose:** what moves the book: bump-and-reprice DV01 (per 1bp), CS01, DIV01, delta, vega, gamma
(central bumps), 1-day theta, key-rate ladders and cross-gamma.

**Inputs:** `trades` (required), `ladder_vertices`; in `advanced`: `market_data`, `reporting_currency`, `risk_classes` (`IR`, `CR`, `EQ`,
`CM`, `FX`, `OT`), `factors`, `include_theta` (true), `include_ladders` (true), `bump_method` (`central`, `forward`),
`cross_gamma_factors` (2 or more factor keys).

**Outputs:** `base_pv`, `by_risk_class` (`risk_class`, `measure`, `value`), `gamma_by_risk_class`,
`by_trade`, `theta`, `by_factor`, `ladders` (`field`, `name`, `measure`, `buckets`), `cross_gamma`,
`errors`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4}],
 "ladder_vertices": "frtb_girr"}
```

```text
Sensitivities in USD for 1 trade(s): DV01 4,561.84
by_risk_class [{"risk_class": "IR", "measure": "dv01", "value": 4561.84}]; theta {"IRS-5Y": 925.36}
ladders: forward_curves/SOFR dv01 {"2.0": 78.28, "3.0": 183.89, "5.0": 4217.99, ...}
```

### qlrisk_value_at_risk

**Purpose:** market-risk VaR and Expected Shortfall.

**Inputs:** `trades`, `method` (`historical`, `age_weighted`, `filtered_historical`, `monte_carlo`,
`parametric`), `confidence_pct` (99), `es_confidence_pct` (97.5), `horizon_days` (1); in `advanced`:
`market_data`, `reporting_currency`, `history`, `mode` (`portfolio`, or `pnl_series` with `pnl` and
optional `weights`), `lookback` (250), `revaluation` (`full`, `taylor`), `age_decay` (0.98),
`ewma_lambda`, `mc_paths` (5000), `mc_distribution` (`normal`, `student_t`), `mc_dof` (5), `seed` (7),
`decomposition` (true), `group_by` (trade id → group), `include_stressed_var`, `stress_window` (250),
`svar_horizon_days` (10), `liquidity` (`spreads_bp`: trade id → the full bid-ask spread in basis points
of the position value, of which qlrisk charges half as the exit cost; `horizon_days`).

**Outputs:** `var` and `es` (`measure`, `value` as a positive loss, `confidence`, `horizon_days`,
`method`, `n_scenarios`, `contributions`, `tail_scenarios`), `decomposition` (`component`, `incremental`,
`standalone`, `by_group`), `stressed_var`, `liquidity` (`liquidation_cost`, `liquidity_adjusted_var`);
in `pnl_series` mode `var`, `es`, `var_1d`, `es_1d`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4},
            {"product": "EquityOption", "trade_id": "SPX-P", "maturity": "6M", "notional": 1000000, "ticker": "SPX", "strike": 5000, "option_type": "put"}],
 "method": "historical", "horizon_days": 10, "advanced": {"include_stressed_var": true}}
```

```text
historical VaR 99.0% 10d 204,153.91 USD; ES 97.5% 193,288.73; SVaR 561,570.24
var.contributions {"IRS-5Y": 186413.37, "SPX-P": 17740.54}
```

Liquidity-adjusted, the 5m ACME bond with a 40bp bid-ask spread and a 5-day exit
(`"liquidity": {"spreads_bp": {"ACME-5Y": 40}, "horizon_days": 5}`, valued 2026-10-09): 1-day VaR
29,037.60 USD, `liquidation_cost` 9,773.63 (half of 0.40% of the bond's value), `liquidity_adjusted_var`
74,703.67; `qlrisk_inputs.liquidity` shows `{"spreads": {"ACME-5Y": 0.004}, "horizon_days": 5}`.

### qlrisk_backtest

**Purpose:** validate a risk model.

**Inputs:** `trades`, `mode`, `confidence_pct` (99), `test_days` (250); the rest in `advanced`. `mode`: `portfolio` (the book's historical VaR and ES over `test_days` after `lookback`
(250), plus PLA; `include_series` returns the daily `hpl`, `rtpl`, `var`, `es`), `var_series` (`pnl`,
`var_forecasts`, `labels`), `es_series` (`pnl`, `var_forecasts`, `es_forecasts`), `pla` (`hpl`, `rtpl`);
`es_confidence_pct` (97.5). Forecasts are positive losses.

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

**Inputs:** `trades` (required), `end_shocks`, `end_valuation_date` (the time roll); in `advanced`:
`market_data` (the start), `end_market_data` (instead of `end_shocks`), `reporting_currency`.

**Outputs:** `start`, `end`, `total` (`actual`, `theta`, `unexplained` and one entry per risk class),
`trades` (`actual`, `theta`, `by_risk_class`, `unexplained`, `top_factors`).

```json
{"trades": [{"product": "EquityOption", "trade_id": "SPX-P", "maturity": "6M", "notional": 1000000, "ticker": "SPX", "strike": 5000, "option_type": "put"}],
 "end_shocks": [{"factor": "EQ.SPX", "size_pct": -5, "shock_type": "relative"}], "end_valuation_date": "2026-10-12"}
```

```text
P&L 2026-10-09 -> 2026-10-12: actual 20,107.87 USD, theta -257.87, unexplained 216.67
```

### qlrisk_stress_test

**Purpose:** stress a book.

**Inputs:** `trades` (required), `mode`, `scenarios`, `custom_scenarios`, `target_loss`; in `advanced`: `market_data`, `reporting_currency`, `history`, `lookback`, `top_n`. `mode`: `library` (qlrisk's
historical crises, all or `scenarios`: `1987_black_monday`, `1998_ltcm_russia`, `2008_gfc_lehman`,
`2010_euro_crisis`, `2013_taper_tantrum`, `2016_brexit`, `2020_covid`, `2022_rates_shock`,
`2023_regional_banks` in qlrisk today; the schema reads them from qlrisk), `custom` (`custom_scenarios`:
`{name, shocks}` with [shocks](#shocks), or `{name, definition}`, a stylised stress: `equity_pct`,
`vol_pct`, `credit_pct`, `commodity_pct`, `fx_usd_pct` (every currency against USD; -10 = USD 10%
stronger) and `fx_pct` (currency → move) as relative moves in percent, and `rates_bp` as an absolute move
in basis points, or `[short_end, long_end]` for a 2y-10y twist; qlrisk moves credit spreads relatively, so
`credit_pct` 100 doubles them), `reverse` (`target_loss`, `history`, `lookback`, `top_n`). `qlrisk_catalog`
topic `stress_scenarios` shows the library in the same units (`2008_gfc_lehman`: `equity_pct` -40,
`vol_pct` 200, `rates_bp` [-200, -100], `credit_pct` 200, `fx_usd_pct` -12, `commodity_pct` -45).

**Outputs:** `base_pv`, `results` worst first (`scenario`, `pnl`, `by_trade`, `description`), `worst`,
`qlrisk_inputs` (each scenario's shocks or definition as qlrisk received them); reverse: `target_loss`,
`achieved_loss`, `scale`, `sigma_distance`, `top_moves`, `shocks` (in the units above, plus `qlrisk_size`,
so one can be sent back as a custom shock).

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4},
            {"product": "EquityOption", "trade_id": "SPX-P", "maturity": "6M", "notional": 1000000, "ticker": "SPX", "strike": 5000, "option_type": "put"}],
 "mode": "custom", "custom_scenarios": [
   {"name": "rates +100bp", "shocks": [{"risk_classes": ["IR"], "shape": "parallel", "size_bp": 100}]},
   {"name": "SPX -20%", "shocks": [{"factor": "EQ.SPX", "shock_type": "relative", "size_pct": -20}]},
   {"name": "risk off", "definition": {"equity_pct": -20, "vol_pct": 50, "credit_pct": 50, "rates_bp": -50}}]}
```

```text
3 stress scenario(s); worst risk off P&L -87,108.25 USD
risk off      -87,108.25   (IRS-5Y -230,866.48, SPX-P 143,758.23)
SPX -20%      126,050.07   (SPX-P 126,050.07)
rates +100bp  443,545.84   (IRS-5Y 445,355.39, SPX-P -1,809.55)
qlrisk_inputs["custom_scenarios[2].definition"] {"equity": -0.2, "vol": 0.5, "rates": -0.005, "credit": 0.5, ...}
```

With the swap and the SPX put and no `mode`, the library's worst is `2008_gfc_lehman` (-423,260.25 USD); a
reverse stress to a 500,000 loss finds a move 19.04 sigma away.

### qlrisk_frtb_sa_capital

**Purpose:** FRTB Standardised Approach capital (MAR21-23).

**Inputs:** `trades`, `mode`; the rest in `advanced`. `mode`: `portfolio` (default) with `trades`, `market_data`, `reporting_currency`,
`curve_currency`, `credit_buckets`, `equity_buckets`, `commodity_buckets`, `vol_underlyings`, `ratings`,
`seniority`, `exotic`, `other_residual`, `csr_sector_gamma`, `include_curvature`;
`sbm_from_sensitivities` with `frtb_sensitivities` (`risk_class`, `risk_type`, `bucket`, `name`, `tenor`,
`sensitivity`, `risk_weight`); `drc_from_positions` with `drc_positions` (`obligor`, `rating`,
`notional`, `market_value`, `maturity`, `seniority`, `bucket`, `trade_id`).

**Outputs:** `total`, `summary` (per component, `SBM`, `DRC`, `RRAO`, `TOTAL`), `sbm` (`total`,
`scenario`, `by_scenario`, `by_component`, `by_bucket`, `skipped_factors`), `drc` (`total`, `by_bucket`,
`net_jtd`, `hbr`), `rrao`.

```json
{"trades": [...the swap and the SPX put...], "advanced": {"equity_buckets": {"SPX": 12}, "vol_underlyings": {"eq_vol": "SPX"}}}
```

```text
FRTB SA capital 480,891.53 USD: SBM 480,891.53, DRC 0.00, RRAO 0.00; unmapped factors ['DIV.SPX.1Y', 'DIV.SPX.5Y']
```

### qlrisk_frtb_ima_capital

**Purpose:** FRTB Internal Models Approach (MAR31/33).

**Inputs:** `mode`: `full` (default: IMCC, SES for `nmrf`, IMA DRC from `ratings`, capital), `imcc`,
`lh_es`, `liquidity_horizons` (`small_caps`, `high_yield`), `rfet` (`as_of`, `observations`: factor →
dates of real prices), `ima_drc` (`drc_positions`, `n_sims`, `global_correlation`, `sector_correlation`,
`sectors`, `drc_confidence`, `seed`), `capital` (`imcc`, `ses`, `drc`, `multiplier`, `imcc_avg60`,
`ses_avg60`). Book modes take `trades`, `market_data`, `history`, `current_window`, `stress_window`,
`rho`, `revaluation`, `reduced_set`, `liquidity_horizons` (factor → 10/20/40/60/120), `idiosyncratic`,
`seniority`, `multiplier`, `es_confidence_pct` (97.5); `drc_confidence_pct` (99.9) for the DRC. Only
`trades` and `mode` are essentials; the rest is in `advanced`.

**Outputs:** `imcc` (`imcc`, `es_unconstrained`, `es_by_class`, `stress_window`, `ratio`, `details`),
`ses` (`ses`, `by_factor`), `drc` (`drc`, ...), `capital`; `lh_es`: `es`, `components`; `rfet`:
`modellable`, `non_modellable`; `liquidity_horizons`: factor → horizon.

```json
{"mode": "capital", "advanced": {"imcc": 1000000, "ses": 200000, "drc": 100000}}
```

```text
IMA capital 1,800,000.00
```

### qlrisk_basel25_capital

**Purpose:** Basel 2.5 capital = max(VaR, m × avg60 VaR) + max(SVaR, m × avg60 SVaR).

**Inputs:** `var_series`, `svar_series`, `exceptions`; or `trades` (with `market_data`, `history` in `advanced`) to
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
`market_data`, `time_horizon` (years, 5), `num_scenarios` (2000), `confidence_pct` (95)); `calculator`
(`measure`: `ce`, `ee`, `eee`, `pfe`, `peak`, `stressed`; `inputs` and `config` as the calculator defines
them, listed by `qlrisk_catalog` topic `calculators`); `wrong_way` (`credit_factor` such as `CR.GLOBEX.5Y`,
`history`, `shock_sigmas` (3), `horizon_days` (10), `lookback`, `top_n`).

**Outputs:** profiles: `trades` (`time_grid`, `expected_exposure`, `potential_future_exposure`,
`effective_ee`, `peak_exposure`, `epe`, `effective_epe`, `cva`); calculator: `measure`, `result` (the
calculator's result), `headline`; wrong-way: `base_exposure`, `conditional_exposure`, `ratio`,
`spread_move`, `top_moves`. Essentials are `trades`, `mode`, `measure`, `inputs`; the rest is in
`advanced`. qlrisk's exposure profile leaves `cva` at 0.0 for some products (the swap among them); the result
then carries a warning pointing to `qlrisk_xva`.

```json
{"mode": "calculator", "measure": "pfe", "inputs": {"current_mtm": 100000, "notional": 10000000, "remaining_maturity_years": 5, "volatility_pct": 1}}
```

```text
PFE: 212,925.17      (qlrisk_inputs.inputs: remaining_maturity 5, volatility 0.01)
```

Calculator inputs are in the tools' units ([table](#units-of-qlrisks-own-objects)): `volatility_pct` is the
annual volatility of the MTM in percent of notional, `margin_period_of_risk_days` business days (10 by
default), the stressed calculator's `rate_shock_bp` and `credit_shock_bp` basis points, `fx_shock_pct`
percent and `volatility_shock_pct` a relative change (150 = volatility x 2.5). `config.confidence_pct`
sets the PFE confidence (qlrisk reads it in a base class the schema reader misses, so the tool adds it):
99 gives `PFE: 270,070.20` for the example.

### qlrisk_saccr

**Purpose:** SA-CCR exposure at default.

**Inputs:** `trades`, `mode`, `csa` (the rest in `advanced`). `mode`: `netting_sets` (default; `trades`, `market_data`, `reporting_currency`, `csa`: netting
set → `margined`, `collateral`, `threshold`, `minimum_transfer_amount`, `nica`, `mpor_days`;
`index_names`), `trades` (stand-alone per trade), `calculator` (`calculator_input`: `netting_set_id`,
`trades` as `{asset_class, notional, maturity, mtm, ...}`, `collateral`, `variation_margin`, `threshold`,
`minimum_transfer_amount`, `margin_period_of_risk`, `is_margined`).

**Outputs:** `netting_sets` (`netting_set`, `mtm`, `collateral`, `replacement_cost`, `addon_by_class`,
`addon`, `multiplier`, `ead`, `trades`), `ead_total`; trades: per trade `replacement_cost`,
`pfe_add_on`, `ead`, `asset_class`, `hedging_set_contributions`, and `ead_sum`.

```json
{"trades": [{"product": "InterestRateSwap", "trade_id": "IRS-5Y", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4, "counterparty_id": "BANK-A"}],
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
by default, `schedule`, `var`); in `advanced`, `confidence_pct` (99) and `mpor_scaling`. One position gives
its IM; several give the portfolio IM. SIMM `delta_sensitivities` are bucket → sensitivity: for rates
(`irs`, `fra`) the tenor buckets `2w` ... `30y` with **DV01 per 1bp** (as `qlrisk_sensitivities` reports it;
the tool multiplies by 10,000 for qlrisk, whose weights apply per 1.00 of rate), for credit `ig`, `hy`,
`sovereign` with CS01 per 1bp, for equity, FX and commodity a delta in currency per 100% move. A bucket
qlrisk does not know is an error (qlrisk would otherwise apply a 10% weight).

**Outputs:** `result` (`initial_margin`, `im_as_pct_notional`, `method`, `components`), `headline`.

```json
{"method": "simm", "positions": [{"notional": 10000000, "product_type": "irs", "remaining_maturity": 5, "delta_sensitivities": {"5y": 4500}}]}
```

```text
Initial margin (simm): 252,000.00      (5y risk weight 56bp x DV01 4,500)
```

### qlrisk_credit_risk

**Purpose:** credit-risk measures.

**Inputs:** `measure` (`pd`, `lgd`, `ead`, `el`, `economic_capital`, `raroc`), `inputs`, `config`. The
fields and configuration of each come from the qlrisk calculator and are in the tool description and in
`qlrisk_catalog` topic `calculators` (both in the tools' names and units); for example `pd` takes
`credit_rating`, or `asset_value`, `debt_value`, `asset_volatility_pct`, `risk_free_rate_pct`, or
`hazard_rate_pct`, with `config.model` one of `structural`, `reduced_form`, `transition_matrix`,
`logistic`, `historical`. Probabilities, LGDs, recoveries, rates and haircuts are in percent (`pd_pct` 2 =
2%), horizons in years (`time_horizon_years`); the [table](#units-of-qlrisks-own-objects) lists every field.
The result's `qlrisk_inputs` shows the decimals qlrisk received.

**Outputs:** `measure`, `result`, `headline` (PD and LGD are the result itself; others the main field,
e.g. `expected_loss`, `economic_capital`, `raroc`).

```json
{"measure": "pd", "inputs": {"credit_rating": "BBB"}, "config": {"model": "transition_matrix"}}
```

```text
PD: 0.004
```

`{"measure": "el", "inputs": {"pd_pct": 2, "lgd_pct": 45, "ead": 1000000}}` gives `EL: 9,000.00` (qlrisk
received `{"pd": 0.02, "lgd": 0.45, "ead": 1000000}`); `pd_pct` 0.02 gives `EL: 90.00` with the warning
`inputs (el).pd_pct = 0.02 means 0.02%; for 2% send 2`. The structural PD for assets 120, debt 100,
`asset_volatility_pct` 25 and `risk_free_rate_pct` 4 is `PD: 0.222348` (the headline is qlrisk's
probability, a fraction).

### qlrisk_xva

**Purpose:** valuation adjustments and CVA capital.

**Inputs:** `measure`: `cva`, `dva`, `fva`, `kva`, `mva` (`inputs`, `config` from the qlrisk calculator, in
the tools' units; e.g. `cva`: `ee_profile`, `time_grid` (years), `credit_spread_bp`, `recovery_pct`,
`risk_free_rate_pct`, ...; `dva`: `own_pd_curve_pct` and `discount_curve_pct` as tenor → percent); `total` (`inputs`: one
object per adjustment plus `colva` as a number); `sa_cva` (`counterparty` (a credit curve in the market
data), `time_grid`, `expected_exposure`, `recovery_pct` (40), `counterparty_buckets`: name → [MAR50 bucket,
investment grade], `hedges` (trades), `m_cva`, `reference_buckets`, `market_data`, `reporting_currency`);
`ba_cva` (`counterparties`: `name`, `sector`, `investment_grade`, `netting_sets` as [EAD, maturity],
`hedges`; `index_hedges`). Essentials are `measure`, `inputs`, `counterparty`, `time_grid`,
`expected_exposure` and `recovery_pct`; the rest is in `advanced`. Give `notional` in the CVA inputs for a
meaningful `cva_pct`.

**Outputs:** calculators: `result`, `headline`; total: `components` (`cva`, `dva`, `fva`, `kva`, `mva`,
`colva`, `total_xva`), `details`, `convention`; sa_cva: `cva`, `capital`, `by_component`, `by_bucket`;
ba_cva: `result` (`k_reduced`, `capital_reduced`, `scva`, `capital`, ...).

```json
{"measure": "cva", "inputs": {"ee_profile": [2e6, 3e6, 3.5e6, 3e6, 2e6, 1e6], "time_grid": [0.5, 1, 2, 3, 4, 5], "credit_spread_bp": 120}}
```

```text
CVA: 118,737.19      (qlrisk_inputs.inputs.credit_spread 0.012)
```

The same profile as SA-CVA on ACME (`"advanced": {"counterparty_buckets": {"ACME": ["3", true]}}`): CVA 115,136.81 and
capital 294,291.64 USD. BA-CVA for one investment-grade financial with a 10m, 5-year netting set:
1,026,996.36.

### qlrisk_simulate_paths

**Purpose:** Monte Carlo paths of qlrisk's processes (`gbm`, `ou`, `cir`, `heston`, `vasicek`,
`hull_white`, `merton_jump` in qlrisk today; the enum lists only those the generator supports).

**Inputs:** `process`, `initial_value` (required), `drift`, `volatility` (decimals per year), `maturity`
(years), `num_paths`; in `advanced`: `num_steps`, `mean_reversion_speed`, `long_term_mean`, `vol_of_vol`, `correlation`, `initial_variance`,
`jump_intensity`, `jump_mean`, `jump_std`, `seed` (7), `percentiles` ([5, 50, 95]), `sample_paths` (3,
at most 10).

**Outputs:** `time_grid` (at most 60 points), `mean`, `std`, `percentiles`, `terminal` (`mean`, `std`,
`min`, `max`, percentiles), `sample_paths`, `parameters`, `metadata`. The full path matrix is never
returned.

```json
{"process": "gbm", "initial_value": 100, "drift": 0.05, "volatility": 0.2, "maturity": 1, "num_paths": 10000}
```

```text
10000 gbm paths x 252 steps: terminal mean 105.157, std 21.382
```

### qlrisk_risk_report

**Purpose:** every risk in one call with qlrisk's `RiskEngine`.

**Inputs:** `trades`, `use_demo_book`, `measures`, `limits`; the rest in `advanced`. `trades` (with `market_data`, `history`, `reporting_currency`), or `use_demo_book: true` (qlrisk's
demo book: swap, bond, CDS, FX option, equity option, commodity forward, with its history, hierarchy and
FRTB maps); `measures` (`PV`, `SENSITIVITIES`, `VAR`, `ES`, `PARAMETRIC_VAR`, `SVAR`, `STRESS`,
`BACKTEST`, `FRTB_SA`, `EXPOSURE`; the default is qlrisk's default set), `confidence_pct`, `es_confidence_pct`,
`lookback`, `horizon_days` (10), `stress_window`, `hierarchy` (`levels`, `paths`: trade id → path),
`limits`, `frtb` (as in `frtb_sa_capital`), `csa`.

**Outputs:** `as_of`, `currency`, `metrics` (`pv.total`, `var.1d`, `var.10d`, `es.1d`, `svar.10d`,
`frtb_sa.*`, `stress.worst`, `exposure.*`, `<measure>.<risk class>` ...), `by_node`, `notes`,
`measures`, `trades`, `limits`, `stress`, `netting_sets`.

```json
{"use_demo_book": true, "limits": [{"name": "Firm 1d VaR", "metric": "var.1d", "limit": 500000}]}
```

The demo book values itself today with its own market and history, so its date and figures move (a
`market_data` or `history` sent with it is ignored, with a warning):

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
`qlrisk_price_treasury_bond`, `qlrisk_price_interest_rate_swap`, `qlrisk_price_fx_option`. Each one asks
only for **that product's economic terms, in human units**, and keeps everything else in one optional
`advanced` object, so its form on `/tools/<name>/execute` is short:

| Input | Unit and syntax |
|---|---|
| `maturity` | A tenor from the valuation date (`3Y`, `18M`, `6W`, `10D`; `1.5Y` is 18 months) or a date `YYYY-MM-DD`; it must fall after the valuation date. Other dates (`expiry`, `swap_start`, `swap_end`, `settlement`, `fixing`, the FX swap legs) take the same syntax |
| `face_value`, `principal`, `position_value`, `notional` | The amount, named for the product (face value for bonds and bills, principal for deposits and repos, position value for cash equity), in the trade currency, with a default (100 face for bonds, 1,000,000 otherwise) |
| `*_pct` | A rate in **percent**: `coupon_pct` 3 is 3% a year (qlrisk itself takes 0.03); also `rate_pct`, `fixed_rate_pct`, `fra_rate_pct`, `strike_pct` (cap, floor and swaption strikes), `recovery_pct`, `volatility_pct`, `cpr_pct`, `attachment_pct` and the like |
| `*_bp` | A spread in **basis points**: `spread_bp` 25 is 0.25%; also `coupon_bp` (a CDS's running premium, a tranche's spread), `oas_bp`, `rebate_rate_bp`, `fee_rate_bp` |
| frequencies | Words: `annual`, `semi-annual`, `quarterly`, `monthly`, `at maturity` (default the market convention: semi-annual for US treasuries, annual for Bunds and OATs) |
| `currency` | One of qlrisk's currencies, default USD (EUR for Bunds and OATs, GBP for gilts, JPY for JGBs) |
| `option_type`, `pay_fixed`, `swaption_type` | `call`/`put`, true/false, `payer`/`receiver` |
| `advanced` | Optional: trade id and dates, counterparty, `issuer` (its credit curve adds a spread), `position` (`long`/`short`) and the other direction flags, day counts, fallback spots, `market_data`, `reporting_currency`, `include_cash_flows` |

Prices, FX rates, quantities and ratios keep their natural units (an equity strike is a price, an FX strike
a rate). Fields qlrisk gives as a nested object (a TRS's or SFT's `terms`, collateral positions and legs,
borrowed securities) take the same units, field by field ([table](#units-of-qlrisks-own-objects)): a stock
loan's `terms` `{"collateral_margin_pct": 105, "rebate_rate_bp": 50, "haircut_pct": 2,
"stock_volatility_pct": 30, ...}` reach qlrisk as `collateral_margin` 1.05, `rebate_rate` 0.005, `haircut`
0.02, `stock_volatility` 0.3 (in `qlrisk_terms`). Some qlrisk term fields are already in basis points
(`financing_spread`, `interest_spread`, `floating_spread`, `custody_fee_bps`); they get a `_bp` name and pass
unchanged. A margin loan's `initial_margin_pct` and `maintenance_margin_pct` keep their qlrisk names but are
now percent (50, not 0.50). Values outside hard bounds are rejected with the field named (for
example `coupon_pct` above 100, a recovery of 100%, a non-positive face value, a maturity in the past, a
detachment below the attachment, a tenor like `3X`); values outside the usual range (a coupon above 20%, a
rate of 0.03 that probably meant 3%) price but add a line to `warnings`. The names, units, conversions,
bounds and defaults are one table in `sajha/tools/impl/qlrisk/generate.py` (`FIELDS`, `OVERRIDES`,
`NOTIONAL`, `NESTED_*`); a qlrisk field it does not name is passed as is and documented as taking qlrisk's units.

Each description has three lines: what it prices; the inputs with units and defaults; a worked example
with its real result on the sample market. The result is the trade's row of `qlrisk_price_trades` with
`valuation_date` and `reporting_currency` (`npv` and `currency`, `npv_reporting`, `components`, `greeks`,
`risk_measures`, `cash_flows` when asked), plus `qlrisk_terms`: the trade exactly as qlrisk received it, in
qlrisk's units, so the conversion can be checked.

**Finding them.** They are in the `qlrisk` folder of the Tools page with the other qlrisk tools, and in
`tools/list`; `qlrisk_catalog` with topic `products` lists every product with its `pricing_tool`.

**Generated, not written.** The configs (`config/tools/qlrisk/qlrisk_price_*.json`, all with the one
implementation `QlriskPriceProductTool` and the product in their `"product"` key) are written by a
generator that reads qlrisk's product registry:

```bash
python -m sajha.tools.impl.qlrisk.generate            # write the configs; remove those of products that are gone
python -m sajha.tools.impl.qlrisk.generate --check    # report differences, write nothing (exit 1 if any)
```

For each product it builds a small example trade in the tool's own inputs, checks it against the tool's
schema and prices it on the sample market (valued 2026-10-09, so the output is stable); the result goes into
the description and `metadata.example_result`. A product that cannot be priced standalone is skipped and
printed with the reason. `tests/tools/test_qlrisk_tools.py` fails when the files differ from what the
generator would write now, so a qlrisk upgrade that adds, removes or changes products is caught: run the
generator and commit the result. The same tests price every example and check it is plausible for its
asset class (a bond within 70-130% of face, a long option non-negative, a swap at its par rate at zero).

**Example.** A 3-year 3% US treasury with face 100, a 5-year corporate bond with face 5,000,000 on ACME's
credit curve, and a 5-year payer swap (each with `"advanced": {"market_data": {"valuation_date": "2026-10-09"}}`):

```json
qlrisk_price_treasury_bond      {"maturity": "3Y", "face_value": 100, "coupon_pct": 3, "currency": "USD"}
qlrisk_price_corporate_bond     {"maturity": "5Y", "face_value": 5000000, "coupon_pct": 5, "advanced": {"issuer": "ACME"}}
qlrisk_price_interest_rate_swap {"maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4}
```

```text
TreasuryBond on 2026-10-09: NPV 97.85 USD
  qlrisk_terms {"maturity_date": "2029-10-09", "notional": 100, "coupon": 0.03, "frequency": 2, ...}
CorporateBond on 2026-10-09: NPV 4,886,813.03 USD
  components {"maturity": 4.9993, "credit_spread": 0.0120}
InterestRateSwap on 2026-10-09: NPV -22,834.98 USD
  components {"fixed_leg_pv": 1960276.75, "float_leg_pv": 1937441.77, "annuity": 44551744.33, "par_rate": 0.04349}
```

`coupon_pct` 300 is rejected (`'coupon_pct': 300 is greater than the maximum of 100.0`); qlrisk itself
would price a 300% coupon without complaint, which is why the bound lives here.

---

## Calling the Tools

Like any SAJHA tool: MCP `tools/call`, REST, Ask SAJHA, composites and workflows.

```bash
curl -s -X POST http://localhost:3002/api/tools/execute -H "X-API-Key: $SAJHA_KEY" -H 'Content-Type: application/json' \
  -d '{"tool": "qlrisk_price_trades", "arguments": {"trades": [{"product": "InterestRateSwap", "maturity": "5Y", "notional": 10000000, "fixed_rate_pct": 4.4}]}}'
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
