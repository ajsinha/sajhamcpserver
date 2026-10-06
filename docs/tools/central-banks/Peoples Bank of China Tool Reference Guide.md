# Peoples Bank of China Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Data Source and API Key](#data-source-and-api-key)
3. [Tools](#tools)
4. [Tool Reference](#tool-reference)
5. [Response Format](#response-format)
6. [Calling the Tools](#calling-the-tools)
7. [Troubleshooting](#troubleshooting)
8. [Disclaimer](#disclaimer)

---

## Overview

The People's Bank of China tools (prefix `pboc_`) return Chinese rates, bond yields, the USD/CNY exchange rate, money supply, prices and macro indicators. Implementation: `sajha/tools/impl/china_central_bank.py`. The live catalog in the app (Tools page, or `tools/list`) is authoritative.

The tools do **not** call PBoC systems. Every series comes from the St. Louis Fed's [FRED](https://fred.stlouisfed.org/) database, which republishes OECD, IMF, BIS and World Bank series for China. The Loan Prime Rate (LPR) and official FX/gold reserves are not available through these tools.

---

## Data Source and API Key

All data tools need a FRED API key (free at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)). The SAJHA config key for FRED is `fred.api.key`, bound to the `FRED_API_KEY` environment variable in `config/application.yml`; see the [Configuration Reference](../../getting-started/Configuration%20Reference.md).

> **Caution:** In this release the `pboc_` tools do not read `fred.api.key`. Their key lookup (`_get_api_key`) imports `sajha.config.get_api_key_manager`, a module that does not exist, so every data tool currently returns an error instead of data. `pboc_list_series` works because it makes no API call. Until this is fixed, use [`fred_custom_series`](../market-data/FRED%20Tool%20Reference%20Guide.md) with the FRED codes listed by `pboc_list_series`; it uses the same FRED API and the configured key.

Caching is opt-in per tool: add a top-level `"cache_ttl": <seconds>` to a tool's JSON config. The `metadata.rateLimit` and `metadata.cacheTTL` fields in the `pboc_` configs are informational and are not enforced.

---

## Tools

| Tool | Purpose | Main parameter (values) |
|------|---------|-------------------------|
| `pboc_get_cgb_yield` | Government bond / short-term rates | `bond_term`: `10y`, `3m` |
| `pboc_get_policy_rate` | PBoC lending / deposit rate | `rate_type`: `lending`, `deposit` |
| `pboc_get_exchange_rate` | USD/CNY exchange rate | `currency_pair`: `usd_cny` |
| `pboc_get_money_supply` | Monetary aggregates | `aggregate`: `m0`, `m1`, `m2` |
| `pboc_get_inflation` | Consumer and producer prices | `measure`: `cpi`, `core_cpi`, `ppi` |
| `pboc_get_economic_indicator` | Macro indicators | `indicator`: see below |
| `pboc_list_series` | List the series these tools can fetch | `category`: `rates`, `fx`, `money`, `prices`, `economy`, `all` |

No parameter is marked required in the advertised schemas; every tool falls back to the default shown below.

### Common parameters (all data tools)

| Parameter | Type | Description |
|-----------|------|-------------|
| `start_date` | string | Start date, `YYYY-MM-DD` (FRED `observation_start`) |
| `end_date` | string | End date, `YYYY-MM-DD` (FRED `observation_end`) |
| `recent_periods` | integer | Return only the most recent N observations. If omitted and no dates are given, the full available history is returned (oldest first). |

---

## Tool Reference

### pboc_get_cgb_yield

| Parameter | Values | Default | FRED series |
|-----------|--------|---------|-------------|
| `bond_term` | `10y` | `10y` | `IRLTLT01CNM156N` (long-term government bond yield, monthly) |
| | `3m` | | `IR3TIB01CNM156N` (3-month interbank rate, monthly) |

### pboc_get_policy_rate

| Parameter | Values | Default | FRED series |
|-----------|--------|---------|-------------|
| `rate_type` | `lending`, `deposit` | `lending` | `INTDSRCNM193N` (IMF discount rate for China) for both values |

The config description calls this the Loan Prime Rate; the implementation actually returns the IMF discount-rate series, and `lending` and `deposit` map to the same series.

### pboc_get_exchange_rate

| Parameter | Values | Default | FRED series |
|-----------|--------|---------|-------------|
| `currency_pair` | `usd_cny` | `usd_cny` | `DEXCHUS` (CNY per USD, daily) |

Any other pair returns an "Unsupported currency pair" error.

### pboc_get_money_supply

| Parameter | Values | Default | FRED series |
|-----------|--------|---------|-------------|
| `aggregate` | `m0` | `m2` | `MYAGM0CNM189N` |
| | `m1` | | `MYAGM1CNM189S` |
| | `m2` | | `MYAGM2CNM189N` |

### pboc_get_inflation

Returns price indices. (The config description, "China foreign exchange and gold reserves", is wrong; the implementation returns CPI/PPI.)

| Parameter | Values | Default | FRED series |
|-----------|--------|---------|-------------|
| `measure` | `cpi` | `cpi` | `CHNCPIALLMINMEI` (CPI, all items) |
| | `core_cpi` | | `CHNCPICORMINMEI` (CPI less food and energy) |
| | `ppi` | | `CHNPIEAMP01GYM` (PPI) |

### pboc_get_economic_indicator

| Parameter | Values | Default |
|-----------|--------|---------|
| `indicator` | `gdp`, `gdp_growth`, `unemployment`, `industrial_production`, `retail_sales`, `exports`, `imports`, `fdi`, `house_price_index` | `gdp_growth` |

The implementation also accepts any other series id known to the tool set (for example `trade_balance`, `m2`, `cpi`); `pboc_list_series` shows them with their FRED codes.

### pboc_list_series

| Parameter | Values | Default |
|-----------|--------|---------|
| `category` | `rates`, `fx`, `money`, `prices`, `economy`, `all` | `all` |

Returns `{category, count, source, series: [{id, fred_code, label}]}`. Needs no API key.

---

## Response Format

Data tools return:

```json
{
  "series_code": "MYAGM2CNM189N",
  "series_id": "m2",
  "label": "M2 Money Stock",
  "source": "FRED (Federal Reserve Economic Data)",
  "observation_count": 12,
  "observations": [{"date": "2025-01-01", "value": 3.1e14}]
}
```

Unsupported argument values return `{"error": "..."}`; API failures raise an error that the server returns as a tool error.

---

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "pboc_get_money_supply", "arguments": {"aggregate": "m2", "recent_periods": 12}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "pboc_get_money_supply", "arguments": {"aggregate": "m2", "recent_periods": 12}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("pboc_get_money_supply", aggregate="m2", recent_periods=12)
```


---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `No module named 'sajha.config'` or "FRED API key not configured" | Key lookup issue described under [Data Source and API Key](#data-source-and-api-key); use `fred_custom_series` meanwhile. |
| `Unsupported ...` error | The argument value is outside the lists above. |
| `Invalid series or parameters` / `Series not found` | FRED rejected the series or date range; check dates are `YYYY-MM-DD`. Some OECD/IMF series for China are discontinued or updated with long lags. |
| Empty `observations` | No data in the requested range; widen the dates or use `recent_periods`. |

Data notes: Chinese series on FRED are mostly monthly or annual and lag official releases. Times are dates only (no time zone).

---

## Disclaimer

Data is provided for information and research only and is not investment advice. FRED and its upstream sources (OECD, IMF, BIS, World Bank) are the authoritative sources; verify important figures there and at the [People's Bank of China](http://www.pbc.gov.cn/).

---

## Page Glossary

**Key terms referenced in this document:**

- **PBoC (People's Bank of China)**: China's central bank, responsible for monetary policy and financial regulation.
- **CNY/RMB (Chinese Yuan/Renminbi)**: China's official currency.
- **LPR (Loan Prime Rate)**: China's benchmark lending rate for banks (not available through these tools).
- **CGB (Chinese Government Bond)**: Debt securities issued by the Chinese government.
- **M2 Money Supply**: A measure of money supply including cash, checking deposits, and easily convertible near-money.
- **FRED API**: Federal Reserve Economic Data API, the source of all `pboc_` data.

*For complete definitions, see the [Glossary](../../../GLOSSARY.md).*

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
