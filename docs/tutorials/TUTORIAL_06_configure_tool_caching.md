# Tutorial 6: Configure Tool Caching

Cache a tool's results on disk for a set time, so repeated calls with the same arguments skip the upstream API.

## What you'll learn

- How to make a tool cacheable with `cache_ttl`
- How the cache is keyed and where it is stored
- How to watch cache statistics and invalidate entries

## Prerequisites

- A running server using the default local storage backend
- Write access to `config/tools/`
- An administrator JWT as `$TOKEN` for invalidation ([Tutorial 1](TUTORIAL_01_getting_started.md), step 8)

## How it works

Caching is **opt-in per tool**. A tool without `cache_ttl`, or with `cache_ttl: 0`, is never cached. For a cacheable tool, the key is the tool name plus a hash of its arguments, and each entry is a JSON file at `<cache.dir>/<tool_name>/<hash>.json`. On a cache hit, the tool is not executed at all. The same cache serves every entry point: the web UI, REST, MCP and async execution.

Global settings live under `cache:` in `config/application.yml`:

```yaml
cache:
  enabled: ${CACHE_ENABLED:true}          # master switch
  dir: ${CACHE_DIR:data/cache}
  max_files: ${CACHE_MAX_FILES:50000}
  max_file_size_kb: ${CACHE_MAX_FILE_KB:512}   # larger results are not cached
  cleanup_interval_seconds: 300
```

## Steps

### 1. Add `cache_ttl` to the tool config

Tool configs sit directly in `config/tools/`, one file per tool, named after the tool. Open the tool's file, for example `config/tools/fred_gdp.json`, and add `cache_ttl` (in seconds) at the top level:

```json
{
  "name": "fred_gdp",
  "cache_ttl": 3600,
  "...": "rest of the config unchanged"
}
```

Choose the TTL by how fast the data changes. As a rough guide:

| Kind of tool | Suggested TTL |
|--------------|---------------|
| Calculators | 0 (deterministic and fast, so don't cache) |
| FRED, ECB, World Bank and other macro data | 3600 |
| FMP, OpenBB, Alpha Vantage | 300 |
| CoinGecko | 60 |
| Yahoo Finance quotes | 30 |
| Search and web crawl | 600 |

### 2. Let the server reload the tool

With the local storage backend, the tools registry polls `config/tools/` every few seconds. A changed file is unloaded and reloaded, so the new TTL applies within about five seconds, with no restart. An admin can also force a full reload with `POST /api/admin/tools/reload`.

### 3. Call the tool twice and check the statistics

Run the tool twice with identical arguments, from the UI, REST or MCP. Then look at the statistics:

```bash
curl -s http://localhost:3002/api/cache/stats -H "Authorization: Bearer $TOKEN"
# -> {"type": "file", "cache_dir": "data/cache", "size": 1, "tools_cached": 1,
#     "hits": 1, "misses": 1, "writes": 1, "hit_rate": 50.0, "enabled": true, ...}
```

The same numbers appear on **Admin → System monitor** (`/admin/system-monitor`) in the **Tool Cache** card: Hit Rate, Cached Items, Total Hits, Total Misses and Disk Usage.

### 4. Invalidate

To invalidate a single tool's entries (admin only):

```bash
curl -s -X POST http://localhost:3002/api/cache/invalidate \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"tool_name": "fred_gdp"}'
# -> {"invalidated": true, "tool_name": "fred_gdp"}
```

Send `{}`, or no body at all, to clear everything. The **Invalidate All** button on the System monitor's Tool Cache card does the same.

## What next

- [Storage Guide](../getting-started/Storage%20Guide.md): where `data/cache` lives on each storage backend
- [Architecture](../architecture/Architecture.md)
- Next tutorial: [Submit Async Tool Execution](TUTORIAL_07_submit_async_tool_execution.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
