# Google Search Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Calling the Tool](#calling-the-tool)
4. [google_search](#google_search)
5. [Usage Examples](#usage-examples)
6. [Errors and Troubleshooting](#errors-and-troubleshooting)
7. [Limitations](#limitations)
8. [See Also](#see-also)

---

## Overview

`google_search` searches the web through the Google Custom Search JSON API
(`https://www.googleapis.com/customsearch/v1`). It supports web and image
search, site restriction, date restriction, SafeSearch and result language.

| Item | Value |
|------|-------|
| Tool | `google_search` |
| Implementation | `sajha.tools.impl.google_search_tool_refactored.GoogleSearchTool` |
| Tool config | `config/tools/google_search.json` |
| Credentials | Google API key and Programmable Search Engine ID |

---

## Configuration

The tool config references two configuration keys, which are defined in
`config/application.yml` and normally supplied through environment variables:

| Config key | Environment variable | Used in tool config as |
|------------|----------------------|------------------------|
| `google.api.key` | `GOOGLE_API_KEY` | `"api_key": "${google.api.key}"` |
| `google.search.engine.id` | `GOOGLE_SEARCH_ENGINE_ID` | `"search_engine_id": "${google.search.engine.id}"` |

See the [Configuration Reference](../../getting-started/Configuration%20Reference.md)
for how `${...}` placeholders and environment variables are resolved.

### Obtaining credentials

1. In the [Google Cloud Console](https://console.cloud.google.com), enable the
   **Custom Search API** for a project and create an API key under
   *APIs & Services → Credentials*. Restrict the key to the Custom Search API.
2. In [Programmable Search Engine](https://programmablesearchengine.google.com),
   create a search engine (search the entire web, or limit it to chosen sites)
   and copy its **Search engine ID**.
3. Export both values and restart (or hot-reload) the server:

```bash
export GOOGLE_API_KEY=AIza...
export GOOGLE_SEARCH_ENGINE_ID=0123456789abcdef0
```

Quotas and pricing are set by Google; check the Custom Search JSON API
documentation for the current free daily allowance and paid tiers.

### Demo mode

If either credential is empty, the tool runs in **demo mode**: it returns a
handful of placeholder results (example.com / Wikipedia-style links) and a
`note` field saying `Demo mode - Configure API key and Search Engine ID for real results`.
Use it to test wiring only.

---

## Calling the Tool

Over MCP, send a JSON-RPC `tools/call` to `POST /mcp` (an `Mcp-Session-Id`
header is optional):

```bash
curl -s http://localhost:3002/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SAJHA_TOKEN" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"google_search","arguments":{"query":"model context protocol"}}}'
```

Over REST, `POST /api/tools/execute`:

```bash
curl -s http://localhost:3002/api/tools/execute \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SAJHA_API_KEY" \
  -d '{"tool":"google_search","arguments":{"query":"model context protocol"}}'
# -> {"success": true, "result": {...}}
```

Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. Adjust
host and port to your deployment. For protocol details see the
[MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md).

---

## google_search

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | – | Search query |
| `num_results` | integer | No | `10` | Results to return, 1–10 (Google API maximum per request) |
| `start` | integer | No | `1` | 1-based index of the first result, for pagination |
| `safe_search` | string | No | `medium` | `off`, `medium` or `high` |
| `search_type` | string | No | `web` | `web` or `image` |
| `site` | string | No | – | Restrict to a domain; the tool prepends `site:<domain>` to the query |
| `date_restrict` | string | No | – | `dN`, `wN`, `mN` or `yN` (past N days/weeks/months/years), e.g. `d7`, `m3`, `y1` |
| `language` | string | No | `en` | Result language, sent as `lr=lang_<code>` (e.g. `en`, `es`, `fr`, `de`, `ja`) |

### Result

```json
{
  "query": "site:wikipedia.org machine learning",
  "totalResults": "1234000",
  "searchTime": 0.31,
  "count": 10,
  "results": [
    {
      "title": "Machine learning - Wikipedia",
      "link": "https://en.wikipedia.org/wiki/Machine_learning",
      "snippet": "Machine learning (ML) is a field of study ...",
      "displayLink": "en.wikipedia.org"
    }
  ]
}
```

- `query` echoes the query actually sent (including any `site:` prefix).
- `totalResults` is Google's estimate, returned as a string.
- For `search_type: "image"`, each result also has an `image` object with
  `thumbnailLink`, `contextLink`, `height` and `width`.

---

## Usage Examples

Arguments only; wrap them in either call form shown above.

```json
{"query": "machine learning", "site": "wikipedia.org"}
```

```json
{"query": "climate change policy", "date_restrict": "m1", "num_results": 5}
```

```json
{"query": "golden gate bridge", "search_type": "image", "num_results": 5}
```

```json
{"query": "inteligencia artificial", "language": "es"}
```

```json
{"query": "photosynthesis for kids", "safe_search": "high"}
```

**Pagination.** Request successive pages with `start` = 1, 11, 21, ... and
`num_results` = 10. Google's API does not serve results beyond roughly the
first 100.

---

## Errors and Troubleshooting

The tool raises an error (returned as a tool error over MCP, or
`{"success": false, "error": ...}` over REST) in these cases:

| Message | Cause | Fix |
|---------|-------|-----|
| `'query' is required` | Missing `query` | Supply a query |
| `Invalid search parameters` | HTTP 400 from Google | Check `date_restrict` format, `num_results` ≤ 10, `start` ≥ 1 |
| `API key invalid or quota exceeded` | HTTP 403 | Verify `google.api.key`, that the Custom Search API is enabled, and your daily quota |
| `Search failed: HTTP <code>` | Other HTTP error | Retry later; check Google Cloud status |
| `Search failed: <reason>` | Network or parsing error | Check outbound connectivity from the server |

If results look like placeholders, the tool is in demo mode — one of the two
config keys is empty.

An empty `results` list with `count: 0` is a valid response (no matches).

---

## Limitations

- At most 10 results per call; deep pagination is capped by Google.
- Coverage depends on how the Programmable Search Engine is configured (whole
  web vs. listed sites).
- Snippets are short; fetch full pages with the
  [Web Crawler tools](Web%20Crawler%20Tool%20Reference%20Guide.md) if you need
  page content.
- No server-side result caching is performed by the tool itself.

---

## See Also

- [Tavily Search Tool Reference Guide](Tavily%20Search%20Tool%20Reference%20Guide.md) — AI-oriented search with generated answers
- [Wikipedia Search Tool Reference Guide](Wikipedia%20Search%20Tool%20Reference%20Guide.md)
- [Glossary](../../../GLOSSARY.md)
- Google: [Custom Search JSON API](https://developers.google.com/custom-search/v1/overview)

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
