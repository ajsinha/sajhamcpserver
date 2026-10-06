# Financial Calculators Tool Reference Guide

## Overview

The `calc_*` tools (implementation `sajha/tools/impl/calc_tools.py`) are pure-math financial calculators. They need no API key and run locally; the only exception is `calc_currency_converter`, which fetches live rates from the free `open.er-api.com` endpoint.

Rates, returns and volatilities are passed **in percent** (e.g. `5.0` for 5%), and percentage outputs are returned in percent.

## Tools

| Tool | Description | Parameters (required in **bold**) | Output |
|------|-------------|-----------------------------------|--------|
| `calc_compound_interest` | Future value with periodic compounding | **principal**, **rate** (%), **years**, compounds_per_year (default 12) | `future_value`, `total_interest` |
| `calc_present_value` | Present value of a future sum | **future_value**, **rate** (%), **years** | `present_value` |
| `calc_future_value` | Future value of a present sum | **present_value**, **rate** (%), **years** | `future_value` |
| `calc_npv` | Net present value | **discount_rate** (%), **cash_flows** (array, first item the negative initial investment) | `npv` |
| `calc_irr` | Internal rate of return | **cash_flows** (array) | `irr` (%) |
| `calc_loan_amortization` | Monthly payment, total interest and yearly schedule (has an MCP Apps chart view) | **principal**, **annual_rate** (%), **months** (integer) | `monthly_payment`, `total_paid`, `total_interest`, `yearly_schedule` |
| `calc_bond_price` | Bond price from yield | face_value (default 1000), **coupon_rate** (%), **yield_rate** (%), **years** (integer) | `price` |
| `calc_black_scholes` | European call and put prices | **stock_price**, **strike**, **time_years**, **risk_free_rate** (%), **volatility** (%) | `call_price`, `put_price`, `d1`, `d2` |
| `calc_dcf_model` | DCF enterprise value | **free_cash_flow**, **growth_rate** (%), **wacc** (%), terminal_growth (%, default 2), projection_years (default 5) | `enterprise_value`, `pv_cash_flows`, `terminal_value_pv` |
| `calc_capm` | Expected return via CAPM | **risk_free_rate** (%), **beta**, **market_return** (%) | `expected_return`, `risk_premium` |
| `calc_wacc` | Weighted average cost of capital | **equity_value**, **debt_value**, **cost_of_equity** (%), **cost_of_debt** (%), **tax_rate** (%) | `wacc`, `equity_weight`, `debt_weight` |
| `calc_sharpe_ratio` | Sharpe ratio | **portfolio_return** (%), **risk_free_rate** (%), **volatility** (%) | `sharpe_ratio` |
| `calc_sortino_ratio` | Sortino ratio | **portfolio_return** (%), **risk_free_rate** (%), **downside_deviation** (%) | `sortino_ratio` |
| `calc_beta` | Beta of a stock against the market | **stock_returns** (array), **market_returns** (array) | `beta`, `data_points` |
| `calc_correlation` | Pearson correlation | **series_x** (array), **series_y** (array) | `correlation`, `data_points` |
| `calc_max_drawdown` | Maximum peak-to-trough decline | **portfolio_values** (array) | `max_drawdown` (%) |
| `calc_percentage_change` | Percentage change | **old_value**, **new_value** | `percentage_change` |
| `calc_currency_converter` | Currency conversion at live rates | from (default `USD`), to (default `EUR`), amount (default 1) | `rate`, `converted` |
| `calc_retirement` | Retirement savings projection | **current_savings**, **annual_contribution**, **return_rate** (%), **years** (integer) | `final_balance`, `total_contributed` |

## Usage Examples

Over MCP, send `tools/call` to `POST /mcp`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "calc_black_scholes",
    "arguments": {"stock_price": 150, "strike": 155, "time_years": 0.5,
                  "risk_free_rate": 5.0, "volatility": 25.0}
  }
}
```

Over REST, `POST /api/tools/execute` with `{"tool": "<name>", "arguments": {...}}`; the response is `{"success": true, "result": {...}}`. Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. See the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol details.

More argument examples:

```json
{"tool": "calc_loan_amortization", "arguments": {"principal": 300000, "annual_rate": 6.5, "months": 360}}

{"tool": "calc_dcf_model", "arguments": {"free_cash_flow": 100, "growth_rate": 5.0, "wacc": 9.0,
                                          "terminal_growth": 2.5, "projection_years": 5}}

{"tool": "calc_npv", "arguments": {"discount_rate": 8.0, "cash_flows": [-1000, 300, 400, 500]}}

{"tool": "calc_currency_converter", "arguments": {"from": "USD", "to": "JPY", "amount": 250}}
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
