# Financial Calculators — Tool Reference Guide

**Version:** 4.0.0 · **Tools:** 19 · **API Key Required:** No (pure math, no external APIs)

---

## Overview

SAJHA includes 19 pure-math financial calculator tools. These require no API keys or network access — all computation is done locally.

## Tool List

| Tool | Description | Key Inputs |
|------|-------------|------------|
| `calc_compound_interest` | Compound interest calculation | principal, rate, years, compounds_per_year |
| `calc_present_value` | Present value of future cash flow | future_value, rate, years |
| `calc_future_value` | Future value of present amount | present_value, rate, years |
| `calc_npv` | Net present value of cash flows | rate, cash_flows (array) |
| `calc_irr` | Internal rate of return | cash_flows (array) |
| `calc_loan_amortization` | Loan payment schedule | principal, annual_rate, years |
| `calc_bond_price` | Bond pricing from yield | face_value, coupon_rate, years, yield_rate |
| `calc_black_scholes` | European option pricing | stock_price, strike, time_years, risk_free_rate, volatility |
| `calc_dcf_model` | Discounted cash flow valuation | cash_flows, growth_rate, discount_rate, terminal_growth |
| `calc_capm` | Capital Asset Pricing Model | risk_free_rate, beta, market_return |
| `calc_wacc` | Weighted average cost of capital | equity, debt, cost_of_equity, cost_of_debt, tax_rate |
| `calc_sharpe_ratio` | Risk-adjusted return (Sharpe) | returns (array), risk_free_rate |
| `calc_sortino_ratio` | Downside risk-adjusted return | returns (array), risk_free_rate |
| `calc_beta` | Stock beta vs market | stock_returns, market_returns |
| `calc_correlation` | Correlation between two series | series_a, series_b |
| `calc_max_drawdown` | Maximum peak-to-trough decline | prices (array) |
| `calc_percentage_change` | Percentage change | old_value, new_value |
| `calc_currency_converter` | Currency conversion | amount, from_rate, to_rate |
| `calc_retirement` | Retirement savings projection | current_savings, monthly_contribution, years, return_rate |

## Usage Examples

```json
{"tool": "calc_black_scholes", "arguments": {
    "stock_price": 150, "strike": 155, "time_years": 0.5,
    "risk_free_rate": 5.0, "volatility": 25.0
}}

{"tool": "calc_loan_amortization", "arguments": {
    "principal": 300000, "annual_rate": 6.5, "years": 30
}}

{"tool": "calc_dcf_model", "arguments": {
    "cash_flows": [10, 12, 14, 16, 18],
    "growth_rate": 3.0, "discount_rate": 10.0, "terminal_growth": 2.5
}}
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
