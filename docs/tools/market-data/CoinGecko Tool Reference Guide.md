# CoinGecko Tool Reference Guide

## Overview

The CoinGecko tools (prefix `cg_`) wrap the public [CoinGecko API v3](https://docs.coingecko.com/): coin prices and charts, coin metadata, exchanges, categories, DeFi and derivatives, NFTs and global market statistics. Implementation: `sajha/tools/impl/coingecko_tools.py`.

## API Key

No key is required; the tools use CoinGecko's free public API. The implementation sends a key in the `x-cg-demo-api-key` header only if a tool config supplies an `api_key`; none of the shipped `cg_` configs do. See the [Configuration Reference](../../getting-started/Configuration%20Reference.md) if you add one.

Coin and exchange arguments use CoinGecko **IDs** (`bitcoin`, `ethereum`, `binance`), not ticker symbols. Use `cg_search` or `cg_coin_list` to find an ID.

## Tools

The tables below are generated from the tool configs in `config/tools/`; the live catalog in the app (Tools page, or `tools/list`) is authoritative. Parameters marked *(required)* must be supplied. Defaults shown are the schema defaults.

### Cryptocurrency

| Tool | Description | Parameters |
|------|-------------|------------|
| `cg_asset_platforms` | Get blockchain asset platforms from CoinGecko — Ethereum, Solana, BSC, Polygon, etc. | — |
| `cg_coin_categories_list` | Get cryptocurrency category list from CoinGecko — DeFi, Gaming, Meme, Layer1, etc. | — |
| `cg_coin_categories_market` | Get crypto categories with market data from CoinGecko — market cap, volume, change per category | — |
| `cg_coin_history` | Get historical crypto data for a specific date from CoinGecko | `id` (required), default `bitcoin`; `date` (required) |
| `cg_coin_info` | Get detailed crypto coin info from CoinGecko — description, links, categories, genesis date | `id` (required), default `bitcoin` |
| `cg_coin_list` | Get full list of all coins on CoinGecko — IDs, symbols, names | — |
| `cg_coin_market_chart` | Get crypto price chart from CoinGecko — historical prices, volumes, market caps | `id` (required), default `bitcoin`; `days`, default `30`; `vs`, default `usd` |
| `cg_coin_markets` | Get top crypto by market cap from CoinGecko — ranked list with prices and 24h change | `order`, default `market_cap_desc`; `limit`, default `50` |
| `cg_coin_ohlc` | Get crypto OHLC candlestick data from CoinGecko | `id` (required), default `bitcoin`; `days`, default `30` |
| `cg_coin_price` | Get current crypto prices from CoinGecko — price, 24h change, market cap for any coin | `ids` (required), default `bitcoin`; `vs`, default `usd` |
| `cg_coin_tickers` | Get exchange tickers for a crypto from CoinGecko — where it trades, bid/ask, volume | `id` (required), default `bitcoin` |
| `cg_companies_holdings` | Get public companies holding BTC/ETH from CoinGecko — Tesla, MicroStrategy, etc. | `coin_id`: bitcoin / ethereum, default `bitcoin` |
| `cg_defi_global` | Get global DeFi market stats from CoinGecko — TVL, DeFi market cap, ETH dominance | — |
| `cg_exchange_info` | Get exchange details from CoinGecko — Binance, Coinbase, Kraken, etc. | `id` (required), default `binance` |
| `cg_exchange_rates` | Get BTC exchange rates to all currencies from CoinGecko | — |
| `cg_exchange_tickers` | Get exchange trading pairs from CoinGecko — all active pairs on an exchange | `id` (required), default `binance` |
| `cg_exchanges_list` | Get crypto exchanges list from CoinGecko — ranked by volume, trust score | `limit`, default `20` |
| `cg_market_global` | Get global crypto market stats from CoinGecko — total market cap, volume, BTC dominance | — |
| `cg_search` | Search CoinGecko for coins, exchanges, categories by keyword | `query` (required) |
| `cg_top_gainers` | Get top crypto gainers (24h) from CoinGecko | — |
| `cg_top_losers` | Get top crypto losers (24h) from CoinGecko | — |
| `cg_trending_coins` | Get trending cryptocurrencies from CoinGecko — most searched coins in last 24h | — |

### Derivatives

| Tool | Description | Parameters |
|------|-------------|------------|
| `cg_derivatives` | Get crypto derivatives data from CoinGecko — futures, perpetuals | — |
| `cg_derivatives_exchanges` | Get crypto derivatives exchanges from CoinGecko | — |

### NFTs

| Tool | Description | Parameters |
|------|-------------|------------|
| `cg_nft_list` | Get NFT collections list from CoinGecko | — |

## Calling the Tools

Every tool can be called over MCP (a `tools/call` request on `POST /mcp`) or over the REST API (`POST /api/tools/execute`). Authenticate with an `X-API-Key: sja_...` header or an `Authorization: Bearer <token>` header. Sessions, protocol versions and headers are covered in the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

**MCP (`POST /mcp`)**

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "cg_coin_price", "arguments": {"ids": "bitcoin,ethereum", "vs": "usd"}}}
```

**REST**

```bash
curl -X POST http://localhost:3002/api/tools/execute \
  -H "X-API-Key: sja_your_key" -H "Content-Type: application/json" \
  -d '{"tool": "cg_coin_price", "arguments": {"ids": "bitcoin,ethereum", "vs": "usd"}}'
```

**Python client SDK**

```python
from sajhaclient import SajhaClient, SajhaConfig

client = SajhaClient(SajhaConfig(base_url="http://localhost:3002", api_key="sja_your_key"))
result = client.execute_tool("cg_coin_price", ids="bitcoin,ethereum", vs="usd")
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
