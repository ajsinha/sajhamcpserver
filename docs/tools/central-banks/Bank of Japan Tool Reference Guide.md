# Bank of Japan Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Data Source and API Key](#data-source-and-api-key)
3. [Tools](#tools)
4. [Advertised Schema](#advertised-schema)
5. [Tool Reference](#tool-reference)
6. [Response Format](#response-format)
7. [Calling the Tools](#calling-the-tools)
8. [Troubleshooting](#troubleshooting)
9. [Disclaimer](#disclaimer)

---

## Overview

The Bank of Japan tools (prefix `boj_`) return Japanese government bond and money-market rates, BoJ policy rates, yen exchange rates, money supply, prices and macro indicators. Implementation: `sajha/tools/impl/japan_central_bank.py`. The live catalog in the app (Tools page, or `tools/list`) is authoritative.

The tools do **not** call the Bank of Japan's Time-Series Data Search. Every series comes from the St. Louis Fed's [FRED](https://fred.stlouisfed.org/) database, which republishes OECD, IMF and BoJ data for Japan.

---

## Data Source and API Key

All data tools need a FRED API key (free at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html)). The SAJHA config key for FRED is `fred.api.key`, bound to the `FRED_API_KEY` environment variable in `config/application.yml`; see the [Configuration Reference](../../getting-started/Configuration%20Reference.md).

Each `boj_` tool config carries `"api_key": "${fred.api.key}"`; the tools also fall back to the `FRED_API_KEY` environment variable. Without a key, the data tools return "FRED API key not configured". `boj_list_series` needs no key because it makes no API call.

Caching is opt-in per tool: add a top-level `"cache_ttl": <seconds>` to a tool's JSON config. The `metadata.rateLimit` and `metadata.cacheTTL` fields in the `boj_` configs are informational and are not enforced.

---

## Tools

| Tool | Purpose | Main parameter (values the implementation accepts) |
|------|---------|-------------------------|
| `boj_get_jgb_yield` | JGB / short-term rate | `bond_term`: `10y`, `3m` |
| `boj_get_policy_rate` | Call-money and discount rates | `rate_type`: `call_money`, `discount` |
| `boj_get_exchange_rate` | Yen exchange rates | `currency_pair`: `usd_jpy`, `eur_jpy` |
| `boj_get_money_supply` | Monetary aggregates | `aggregate`: `m1`, `m2`, `m3` |
| `boj_get_inflation` | Consumer and producer prices | `index_type`: `cpi`, `core_cpi`, `ppi` |
| `boj_get_economic_indicator` | Macro indicators | `indicator`: `gdp`, `unemployment`, `industrial_production`, `trade_balance` |
| `boj_list_series` | List the series these tools can fetch | `category`: `rates`, `fx`, `money`, `prices`, `economy`, `all` |

### Common parameters (all data tools)

| Parameter | Type | Description |
|-----------|------|-------------|
| `start_date` | string | Start date, `YYYY-MM-DD` (FRED `observation_start`) |
| `end_date` | string | End date, `YYYY-MM-DD` (FRED `observation_end`) |
| `recent_periods` | integer | Return only the most recent N observations. If omitted and no dates are given, the full available history is returned (oldest first); the schema default of 10 is not applied server-side. |

---

## Advertised Schema

The `inputSchema` in each `config/tools/boj_*.json` is what `tools/list` advertises, and it matches what the implementation reads:

| Tool | Parameter and values |
|------|----------------------|
| `boj_get_jgb_yield` | `bond_term` (required): `10y`, `3m` (FRED publishes only these maturities for Japan) |
| `boj_get_policy_rate` | `rate_type` (required): `call_money`, `discount` (`policy_rate` and `discount_rate` are accepted as aliases) |
| `boj_get_exchange_rate` | `currency_pair` (required): `usd_jpy`, `eur_jpy` (EUR/JPY is derived from FRED's `DEXJPUS` x `DEXUSEU`, matched by date) |
| `boj_get_money_supply` | `aggregate` (required): `m1`, `m2`, `m3` |
| `boj_get_inflation` | `index_type` (required): `cpi`, `core_cpi`, `ppi` (`measure` is accepted as an alias) |

`boj_get_economic_indicator` and `boj_list_series` have no config schema, so the implementation's own schema is advertised.

---

## Tool Reference

### boj_get_jgb_yield

| `bond_term` | FRED series |
|-------------|-------------|
| `10y` (default) | `IRLTLT01JPM156N` (long-term government bond yield, monthly) |
| `3m` | `IR3TIB01JPM156N` (3-month interbank rate, monthly) |

### boj_get_policy_rate

| `rate_type` | FRED series |
|-------------|-------------|
| `call_money` (default) | `IRSTCI01JPM156N` (call money / interbank immediate rate) |
| `discount` | `INTDSRJPM193N` (discount rate) |

### boj_get_exchange_rate

| `currency_pair` | FRED series |
|-----------------|-------------|
| `usd_jpy` (default) | `DEXJPUS` (JPY per USD, daily) |
| `eur_jpy` | derived: `DEXJPUS` x `DEXUSEU` (FRED has no direct EUR/JPY series) |

### boj_get_money_supply

| `aggregate` | FRED series |
|-------------|-------------|
| `m1` | `MYAGM1JPM189S` |
| `m2` (default) | `MYAGM2JPM189N` |
| `m3` | `MABMM301JPM189S` |

### boj_get_inflation

| `index_type` | FRED series |
|-----------|-------------|
| `cpi` (default) | `JPNCPIALLMINMEI` (CPI, all items) |
| `core_cpi` | `JPNCPICORMINMEI` (CPI less food and energy) |
| `ppi` | `PIEAMP01JPM661N` (PPI) |

### boj_get_economic_indicator

| `indicator` | FRED series |
|-------------|-------------|
| `gdp` (default) | `JPNRGDPEXP` (real GDP) |
| `unemployment` | `LRUNTTTTJPM156S` |
| `industrial_production` | `JPNPROINDMISMEI` |
| `trade_balance` | `JPNXTEXVA01NCMLM` |

### boj_list_series

| Parameter | Values | Default |
|-----------|--------|---------|
| `category` | `rates`, `fx`, `money`, `prices`, `economy`, `all` | `all` |

Returns `{category, count, source, series: [{id, fred_code, label}]}`. Needs no API key.

---

## Response Format

Data tools return:

```json
{
  "series_code": "JPNCPIALLMINMEI",
  "series_id": "cpi",
  "label": "Consumer Price Index (All Items)",
  "source": "FRED (Federal Reserve Economic Data)",
  "frequency": "Unknown",
  "units": "Unknown",
  "observation_count": 12,
  "observations": [{"date": "2025-01-01", "value": 110.2}]
}
```

Unsupported argument values return `{"error": "..."}`; API failures raise an error that the server returns as a tool error.

---

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "boj_get_inflation", "arguments": {"index_type": "cpi", "recent_periods": 12}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "boj_get_inflation", "arguments": {"index_type": "cpi", "recent_periods": 12}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("boj_get_inflation", index_type="cpi", recent_periods=12)
```


---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| "FRED API key not configured" | Set `FRED_API_KEY` (see [Data Source and API Key](#data-source-and-api-key)). |
| `Missing required parameter: index_type` (or `rate_type`, `bond_term`, ...) | The advertised schema requires it; see [Advertised Schema](#advertised-schema). |
| `Unsupported ...` error | The value is outside what the implementation accepts (tables above). |
| `Invalid series or parameters` / `Series not found` | FRED rejected the series or date range; check dates are `YYYY-MM-DD`. Some OECD series for Japan are discontinued or updated with a lag. |
| Empty `observations` | No data in the requested range; widen the dates or use `recent_periods`. |

---

## Disclaimer

Data is provided for information and research only and is not investment advice. FRED and its upstream sources are the authoritative sources; verify important figures there and at the [Bank of Japan](https://www.boj.or.jp/en/statistics/).

---

*Terms used in this guide are defined in the [Glossary](../../../GLOSSARY.md).*

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
