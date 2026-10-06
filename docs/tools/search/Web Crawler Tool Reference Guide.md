# Web Crawler Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Calling the Tools](#calling-the-tools)
4. [Tools](#tools)
   - [check_robots_txt](#check_robots_txt)
   - [crawl_sitemap](#crawl_sitemap)
   - [crawl_url](#crawl_url)
   - [extract_links](#extract_links)
   - [extract_content](#extract_content)
   - [extract_metadata](#extract_metadata)
   - [get_page_info](#get_page_info)
5. [Choosing a Tool](#choosing-a-tool)
6. [Politeness](#politeness)
7. [Errors and Troubleshooting](#errors-and-troubleshooting)
8. [Limitations](#limitations)
9. [See Also](#see-also)

---

## Overview

The Web Crawler tools fetch public web pages over HTTP(S) and parse their HTML
with the Python standard library (`urllib`, `html.parser`,
`urllib.robotparser`). No third-party packages or API keys are needed.

| Tool | Fetches | Purpose |
|------|---------|---------|
| `check_robots_txt` | `/robots.txt` | Is a URL crawlable, and is there a crawl delay? |
| `crawl_sitemap` | sitemap XML | All URLs listed in a site's sitemap |
| `crawl_url` | many pages | Breadth-first crawl up to depth 3 / 100 pages |
| `extract_links` | one page | Hyperlinks, internal/external |
| `extract_content` | one page | Clean text, headings and images |
| `extract_metadata` | one page | Title, meta description/keywords, headings |
| `get_page_info` | one page | Page statistics: heading/link/image counts, size |

Implementation: `sajha.tools.impl.webcrawler_tool_refactored`; tool configs:
`config/tools/check_robots_txt.json`, `crawl_sitemap.json`, `crawl_url.json`,
`extract_links.json`, `extract_content.json`, `extract_metadata.json`,
`get_page_info.json`.

---

## Configuration

No credentials are required. Built-in behaviour:

| Setting | Value |
|---------|-------|
| User-Agent | `Mozilla/5.0 (compatible; WebCrawlerTool/1.0)` |
| Default request timeout | 10 s (`crawl_url` accepts `timeout`) |
| Default delay between `crawl_url` requests | 1.0 s |
| Max crawl depth / pages | 3 / 100 |
| Response decoding | UTF-8, undecodable bytes ignored |

The server needs outbound HTTP(S) access. Proxies, cookies and site logins are
not supported. General configuration is covered in the
[Configuration Reference](../../getting-started/Configuration%20Reference.md).

---

## Calling the Tools

Over MCP, `POST /mcp` with a JSON-RPC `tools/call` (`Mcp-Session-Id` optional):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "crawl_url",
            "arguments": {"url": "https://example.com", "max_depth": 1, "max_pages": 20}}}
```

Over REST, `POST /api/tools/execute`:

```json
{"tool": "crawl_url", "arguments": {"url": "https://example.com", "max_depth": 1}}
```

which returns `{"success": true, "result": {...}}`. Authenticate with
`Authorization: Bearer <token>` or `X-API-Key: <key>`. See the
[MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol
details.

URLs must be absolute, including the scheme (`https://example.com`, not
`example.com`).

---

## Tools

### check_robots_txt

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | – | Domain or specific path to check |
| `user_agent` | string | No | `Mozilla/5.0 (compatible; WebCrawlerTool/1.0)` | User agent to evaluate rules for |

```json
{
  "url": "https://example.com/admin",
  "robots_url": "https://example.com/robots.txt",
  "can_fetch": false,
  "user_agent": "MyBot/1.0",
  "crawl_delay": 5,
  "checked_at": "2026-10-06T10:00:00"
}
```

`crawl_delay` is `null` when robots.txt has no `Crawl-delay` for that agent. If
robots.txt is missing or unreadable, the tool returns `can_fetch: true` with a
`note` and the `error`.

### crawl_sitemap

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Site URL or direct sitemap URL |

If `url` ends with `sitemap.xml` it is tried first; then
`/sitemap.xml`, `/sitemap_index.xml` and `/sitemap1.xml` at the site root. The
first one that yields `<loc>` entries is returned:

```json
{
  "sitemap_url": "https://example.com/sitemap.xml",
  "status_code": 200,
  "url_count": 245,
  "urls": ["https://example.com/", "https://example.com/about"],
  "retrieved_at": "2026-10-06T10:00:00"
}
```

If nothing is found the result is `{"error": "No sitemap found", "attempted_urls": [...], "base_url": ...}`.
A sitemap index returns the child sitemap URLs (not their contents) — call the
tool again on each child. Sitemap locations declared only in robots.txt, or
sitemap URLs not ending in `sitemap.xml`, are not discovered automatically;
gzip-compressed sitemaps are not supported.

### crawl_url

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | – | Start URL |
| `max_depth` | integer | No | `1` | 0–3. 0 = start page only, 1 = plus its links, ... |
| `max_pages` | integer | No | `10` | 1–100 |
| `follow_external` | boolean | No | `false` | Follow links to other domains |
| `respect_robots` | boolean | No | `true` | Check robots.txt for the start URL first |
| `extract_images` | boolean | No | `true` | Per page: `image_count` and up to 10 image URLs |
| `extract_text` | boolean | No | `true` | Per page: first 500 characters of text (`text_preview`) |
| `delay` | number | No | `1.0` | Seconds between requests, 0.5–5.0 |
| `timeout` | integer | No | `10` | Per-request timeout, 5–30 s |

Crawls breadth-first on the same domain (unless `follow_external`). Result:

```json
{
  "start_url": "https://example.com",
  "max_depth": 1,
  "max_pages": 20,
  "pages_crawled": 12,
  "pages": [
    {
      "url": "https://example.com/",
      "depth": 0,
      "status_code": 200,
      "content_type": "text/html; charset=UTF-8",
      "title": "Example",
      "meta_description": "...",
      "link_count": 34,
      "image_count": 5,
      "images": ["https://example.com/logo.png"],
      "text_preview": "Example Domain ...",
      "crawled_at": "2026-10-06T10:00:01"
    }
  ],
  "follow_external": false,
  "respect_robots": true,
  "crawl_duration": 14.2,
  "completed_at": "2026-10-06T10:00:15"
}
```

A page that fails to load appears in `pages` with an `error` field instead of
the page details. If robots.txt disallows the start URL, the result is
`{"error": "Crawling not allowed by robots.txt", "robots_check": {...}, "url": ...}`.
Only the start URL is checked against robots.txt, not every crawled page.

### extract_links

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | – | Page URL |
| `normalize` | boolean | No | `true` | Resolve relative links to absolute and drop fragments |
| `internal_only` | boolean | No | `false` | Return only same-domain links |

Result: `url`, `links` (each `{url, is_internal, is_absolute}`), `link_count`,
`internal_count`, `external_count`, `extracted_at`. Links come from `<a href>`
only.

### extract_content

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | string | Yes | – | Page URL |
| `extract_images` | boolean | No | `true` | Include `images` (`src`, `alt`, `title`) and `image_count` |
| `extract_text` | boolean | No | `true` | Include `text_content` and `content_length` |
| `text_max_length` | integer | No | `5000` | 100–50,000; longer text is truncated with `...` |

Always returns `url`, `status_code`, `title`, `headings` (`h1`, `h2`, `h3` lists) and
`extracted_at`. Text is produced by stripping tags and collapsing whitespace; inline `<script>` / `<style>` contents are not removed, so expect some noise on script-heavy pages.

### extract_metadata

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Page URL |

Result: `url`, `status_code`, `content_type`, `title`, `meta_description`,
`meta_keywords`, `headings` (`h1`/`h2`/`h3` lists), `content_length` (characters of HTML),
`extracted_at`.

### get_page_info

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `url` | string | Yes | Page URL |

Result: `url`, `status_code`, `content_type`, `title`, `meta_description`,
`meta_keywords`, `headings` (`h1_count`, `h2_count`, `h3_count` and the first
five `h1`/`h2`/`h3` texts), `link_count`, `image_count`, `content_length`,
`retrieved_at`.

---

## Choosing a Tool

| Need | Use |
|------|-----|
| Permission check before any crawl | `check_robots_txt` |
| Complete URL list of a site | `crawl_sitemap` (much cheaper than crawling) |
| Discover structure when there is no sitemap | `crawl_url` |
| Text of one page for summarisation / NLP | `extract_content` |
| SEO audit of one page | `extract_metadata` or `get_page_info` |
| Navigation or outbound-link analysis | `extract_links` |

A typical sequence: `check_robots_txt` → `crawl_sitemap` → `extract_content` on
the pages of interest; fall back to `crawl_url` only when no sitemap exists.

---

## Politeness

- Keep `respect_robots: true` and honour any `crawl_delay` returned by
  `check_robots_txt` by setting `delay` at least that high.
- Use the smallest `max_depth` / `max_pages` that answers the question.
- Increase `delay` (2–5 s) for small sites or if you receive HTTP 429/503.
- Check a site's terms of service before crawling it; respect copyright and
  privacy rules for any content you store.

---

## Errors and Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Invalid URL: ...` | Missing scheme or host | Use `https://host/path` |
| Timeout / `<urlopen error ...>` | Slow or unreachable site | Raise `timeout` (crawl_url), check connectivity |
| HTTP 403 / 429 in page errors | Blocked or rate-limited | Increase `delay`, crawl less, or check robots.txt |
| `Crawling not allowed by robots.txt` | Disallowed path | Respect it, or check a different path / user agent |
| `No sitemap found` | Sitemap at a non-standard path | Pass the sitemap URL directly; look for `Sitemap:` in robots.txt |
| SSL certificate error | Invalid certificate on the target | Not bypassable from the tool; contact the site owner |
| Empty text / missing content | Page built by JavaScript | See [Limitations](#limitations) |

Single-page tools raise errors (tool error over MCP, `success: false` over REST);
`crawl_url` records per-page failures inside `pages` and continues.

---

## Limitations

- No JavaScript execution: client-rendered content (SPAs, AJAX-loaded data) is
  not seen.
- No authentication, cookies, sessions or proxy support.
- HTML only; PDFs and other binary resources are not parsed.
- Iframe and shadow-DOM content is not followed.
- Requests are sequential (single-threaded); large crawls are slow by design.
- `crawl_url` holds results in memory and is capped at 100 pages per call.
- robots.txt evaluation uses Python's `urllib.robotparser`, which does not
  implement every wildcard extension.

---

## See Also

- [Google Search Tool Reference Guide](Google%20Search%20Tool%20Reference%20Guide.md) and
  [Tavily Search Tool Reference Guide](Tavily%20Search%20Tool%20Reference%20Guide.md) — find pages to crawl
- [Glossary](../../../GLOSSARY.md)
- [robots.txt specification (RFC 9309)](https://www.rfc-editor.org/rfc/rfc9309)

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
