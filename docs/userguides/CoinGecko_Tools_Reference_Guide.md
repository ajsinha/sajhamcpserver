# CoinGecko — Tool Reference Guide

**Version:** 5.3.0 · **Tools:** 25 · **API Key Required:** No (free public API)

---

## Overview

SAJHA provides 25 CoinGecko tools covering cryptocurrency prices, market data, OHLC charts, exchanges, NFTs, DeFi, derivatives, and market overview. All tools use the free CoinGecko API v3.

## Tool List (25 tools)

### Coin Data (7 tools)

| Tool | Description |
|------|-------------|
| `coingecko_coin_price` | Current price, 24h change, market cap |
| `coingecko_coin_info` | Detailed coin information |
| `coingecko_coin_history` | Historical data for a specific date |
| `coingecko_coin_market_chart` | Price chart data (1d–365d) |
| `coingecko_coin_ohlc` | OHLC candlestick data |
| `coingecko_coin_tickers` | Exchange ticker data for a coin |
| `coingecko_coin_markets` | Ranked coins with market data |

### Discovery & Search (5 tools)

`coingecko_trending_coins`, `coingecko_coin_list`, `coingecko_search`, `coingecko_top_gainers`, `coingecko_top_losers`

### Categories (2 tools)

`coingecko_coin_categories_list`, `coingecko_coin_categories_market`

### Exchanges (3 tools)

`coingecko_exchanges_list`, `coingecko_exchange_info`, `coingecko_exchange_tickers`

### Market Overview (3 tools)

`coingecko_market_global`, `coingecko_defi_global`, `coingecko_exchange_rates`

### Derivatives (2 tools)

`coingecko_derivatives`, `coingecko_derivatives_exchanges`

### Other (3 tools)

`coingecko_nft_list`, `coingecko_asset_platforms`, `coingecko_companies_holdings`

## Usage Example

```json
{"tool": "coingecko_coin_price", "arguments": {"ids": "bitcoin,ethereum", "vs": "usd"}}
{"tool": "coingecko_coin_market_chart", "arguments": {"id": "bitcoin", "days": 90}}
```

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
