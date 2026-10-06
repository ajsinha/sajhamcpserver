# Tavily Search Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Calling the Tools](#calling-the-tools)
4. [Tools](#tools)
   - [tavily_web_search](#tavily_web_search)
   - [tavily_news_search](#tavily_news_search)
   - [tavily_research_search](#tavily_research_search)
   - [tavily_domain_search](#tavily_domain_search)
5. [Result Format](#result-format)
6. [Choosing a Tool](#choosing-a-tool)
7. [Errors and Troubleshooting](#errors-and-troubleshooting)
8. [Limitations](#limitations)
9. [See Also](#see-also)

---

## Overview

The Tavily tools wrap the [Tavily](https://tavily.com) search API
(`POST https://api.tavily.com/search`), a search engine built for LLM agents.
Results carry a relevance score and cleaned page content, and Tavily can
return a short AI-generated answer synthesised from the results.

All four tools share one base class and one API call; they differ in which
Tavily options they fix and which they expose.

| Tool | Tavily `search_depth` | Tavily `topic` | Purpose |
|------|----------------------|----------------|---------|
| `tavily_web_search` | caller (`basic`/`advanced`) | `general` | General web search, optional images |
| `tavily_news_search` | `basic` | `news` | Recent news articles |
| `tavily_research_search` | `advanced` | caller (`general`/`science`/`finance`) | In-depth research, optional raw page content |
| `tavily_domain_search` | `basic` | `general` | Search restricted to / excluding given domains |

Implementation: `sajha.tools.impl.tavily_tool_refactored`; tool configs:
`config/tools/tavily_*.json`.

---

## Configuration

Each Tavily tool config sets `"api_key": "${tavily.api.key}"`. The key
`tavily.api.key` is defined in `config/application.yml` and read from the
`TAVILY_API_KEY` environment variable:

```bash
export TAVILY_API_KEY=tvly-...
```

See the [Configuration Reference](../../getting-started/Configuration%20Reference.md)
for placeholder resolution. Get a key from the Tavily dashboard; quotas and
rate limits depend on your Tavily plan.

### Demo mode

With no key configured, every Tavily tool returns placeholder results
(`example.com` URLs, a canned `answer` when requested, sample images for
`tavily_web_search`). Demo mode is meant for wiring tests only.

---

## Calling the Tools

Over MCP, `POST /mcp` with a JSON-RPC `tools/call` (`Mcp-Session-Id` optional):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "tavily_web_search",
            "arguments": {"query": "latest developments in quantum computing"}}}
```

Over REST, `POST /api/tools/execute`:

```json
{"tool": "tavily_web_search",
 "arguments": {"query": "latest developments in quantum computing"}}
```

which returns `{"success": true, "result": {...}}`. Authenticate with
`Authorization: Bearer <token>` or `X-API-Key: <key>`. See the
[MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol
details.

---

## Tools

### tavily_web_search

General web search.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | – | Search query |
| `search_depth` | string | No | `basic` | `basic` (fast) or `advanced` (more thorough, slower, uses more API credits) |
| `max_results` | integer | No | `5` | 1–20 |
| `include_answer` | boolean | No | `true` | Include Tavily's AI-generated answer |
| `include_images` | boolean | No | `false` | Include related image URLs (`images` field) |

```json
{"query": "machine learning frameworks comparison", "search_depth": "advanced",
 "max_results": 10, "include_images": true}
```

### tavily_news_search

News-optimised search (`topic: news`, `basic` depth).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | – | News search query |
| `max_results` | integer | No | `5` | 1–20 |
| `include_answer` | boolean | No | `true` | Include an AI-generated news summary |

```json
{"query": "artificial intelligence regulations", "max_results": 7}
```

### tavily_research_search

Comprehensive search with `advanced` depth; the answer is always requested.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | – | Research query |
| `topic` | string | No | `general` | `general`, `science` or `finance` |
| `max_results` | integer | No | `10` | 5–20 |
| `include_raw_content` | boolean | No | `false` | Add each page's full content as `raw_content` (large responses) |

```json
{"query": "venture capital trends in biotechnology", "topic": "finance", "max_results": 15}
```

### tavily_domain_search

Search only within, or excluding, given domains. At least one of
`include_domains` or `exclude_domains` must be non-empty, otherwise the tool
fails with `Either 'include_domains' or 'exclude_domains' must be specified`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | – | Search query |
| `include_domains` | array of string | No* | – | Domains to search within, e.g. `["react.dev", "github.com"]` |
| `exclude_domains` | array of string | No* | – | Domains to exclude, e.g. `["pinterest.com"]` |
| `max_results` | integer | No | `5` | 1–20 |
| `include_answer` | boolean | No | `true` | Include AI-generated answer |

\* One of the two is required.

```json
{"query": "PostgreSQL transaction isolation", "include_domains": ["postgresql.org"]}
```

The result additionally echoes `included_domains` / `excluded_domains`.

---

## Result Format

```json
{
  "query": "latest developments in quantum computing",
  "search_depth": "basic",
  "topic": "general",
  "results_count": 5,
  "results": [
    {
      "title": "...",
      "url": "https://...",
      "content": "Cleaned excerpt of the page ...",
      "score": 0.93,
      "published_date": ""
    }
  ],
  "answer": "Short synthesised answer ...",
  "images": ["https://..."]
}
```

| Field | Present when |
|-------|--------------|
| `answer` | `include_answer` is true and Tavily returned one |
| `images` | `tavily_web_search` with `include_images: true` |
| `results[].raw_content` | `tavily_research_search` with `include_raw_content: true` |
| `results[].published_date` | Always present; often empty outside news results |
| `included_domains` / `excluded_domains` | `tavily_domain_search` |

`score` is Tavily's relevance score (0–1, higher is more relevant).

---

## Choosing a Tool

| Need | Use |
|------|-----|
| Quick factual lookup with a summary | `tavily_web_search` (basic) |
| Current events | `tavily_news_search` |
| Literature review, market research, deep dives | `tavily_research_search` |
| Only trusted / official sources | `tavily_domain_search` with `include_domains` |
| Avoid low-quality or social sites | `tavily_domain_search` with `exclude_domains` |

`advanced` depth gives better coverage at higher latency and API cost; prefer
`basic` for interactive use.

---

## Errors and Troubleshooting

| Message | Cause | Fix |
|---------|-------|-----|
| `'query' is required` | Missing `query` | Supply a query |
| `Invalid search parameters` | HTTP 400 | Check parameter ranges and domain list format |
| `Invalid API key` | HTTP 401 | Check `TAVILY_API_KEY` / `tavily.api.key` |
| `Rate limit exceeded` | HTTP 429 | Back off and retry; review your Tavily plan |
| `Search failed: HTTP <code>` / `Search failed: <reason>` | Other HTTP or network errors | Check connectivity to `api.tavily.com` |

Placeholder `example.com` results mean the key is not set (demo mode).

---

## Limitations

- At most 20 results per call.
- Tavily decides crawl freshness and coverage; very recent pages may be missing.
- `include_raw_content` can make responses very large.
- The tools do not cache results themselves.

---

## See Also

- [Google Search Tool Reference Guide](Google%20Search%20Tool%20Reference%20Guide.md)
- [Web Crawler Tool Reference Guide](Web%20Crawler%20Tool%20Reference%20Guide.md) — fetch and parse specific pages
- [Glossary](../../../GLOSSARY.md)
- Tavily API documentation: <https://docs.tavily.com>

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
