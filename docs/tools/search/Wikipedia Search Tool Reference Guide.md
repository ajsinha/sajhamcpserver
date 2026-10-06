# Wikipedia Search Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Configuration](#configuration)
3. [Calling the Tools](#calling-the-tools)
4. [Tools](#tools)
   - [wiki_search](#wiki_search)
   - [wiki_get_summary](#wiki_get_summary)
   - [wiki_get_page](#wiki_get_page)
5. [Typical Workflow](#typical-workflow)
6. [Errors and Troubleshooting](#errors-and-troubleshooting)
7. [Limitations](#limitations)
8. [See Also](#see-also)

---

## Overview

The Wikipedia tools query the MediaWiki Action API of any Wikipedia language
edition (`https://{language}.wikipedia.org/w/api.php`):

| Tool | Purpose | MediaWiki call |
|------|---------|----------------|
| `wiki_search` | Find articles by keyword | `action=query&list=search` |
| `wiki_get_summary` | Lead-section summary of one article | `action=query&prop=extracts\|info\|pageimages\|description\|coordinates` with `exintro` |
| `wiki_get_page` | Full plain-text article with sections and categories | `action=query&prop=extracts\|info\|revisions\|categories\|pageimages` |

Implementation: `sajha.tools.impl.wikipedia_tool`; tool configs:
`config/tools/wiki_search.json`, `wiki_get_summary.json`, `wiki_get_page.json`.
Only the Python standard library is used.

---

## Configuration

No API key is required. Requests are sent with the User-Agent
`Mozilla/5.0 (compatible; MCP-Tools/1.0)` and a 10-second timeout. Wikimedia
applies its own rate limits to anonymous clients; keep request volume modest.

General server configuration is described in the
[Configuration Reference](../../getting-started/Configuration%20Reference.md).

---

## Calling the Tools

Over MCP, `POST /mcp` with a JSON-RPC `tools/call` (`Mcp-Session-Id` optional):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "wiki_search", "arguments": {"query": "Marie Curie"}}}
```

Over REST, `POST /api/tools/execute`:

```json
{"tool": "wiki_search", "arguments": {"query": "Marie Curie"}}
```

which returns `{"success": true, "result": {...}}`. Authenticate with
`Authorization: Bearer <token>` or `X-API-Key: <key>`. See the
[MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol
details.

---

## Tools

### wiki_search

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | – | Topic, keyword or phrase |
| `limit` | integer | No | `5` | 1–20 results |
| `language` | string | No | `en` | Language edition code (`en`, `es`, `fr`, `de`, `zh`, ...) |

```json
{
  "query": "quantum computing",
  "language": "en",
  "result_count": 5,
  "results": [
    {
      "title": "Quantum computing",
      "page_id": 25220,
      "snippet": "A quantum computer is a computer that exploits ...",
      "url": "https://en.wikipedia.org/wiki/Quantum_computing",
      "timestamp": "2026-09-30T12:00:00Z",
      "word_count": 11000
    }
  ],
  "suggestion": null,
  "last_updated": "2026-10-06T10:00:00"
}
```

`snippet` has the search-match highlight markup removed. `suggestion` holds
Wikipedia's spelling suggestion when one exists.

### wiki_get_summary

Provide `query` (title) or `page_id`; one of them is required.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | One of `query` / `page_id` | – | Article title, e.g. `Python (programming language)` |
| `page_id` | integer | One of `query` / `page_id` | – | Wikipedia page ID |
| `language` | string | No | `en` | Language edition |
| `sentences` | integer | No | `3` | 1–10 sentences from the lead section |
| `redirect` | boolean | No | `true` | Follow redirects |
| `include_image` | boolean | No | `true` | Include `thumbnail` and `original_image` |

Result fields: `title`, `page_id`, `url`, `language`, `summary` (same text as
`extract`), `extract`, `thumbnail` / `original_image` (`url`, `width`,
`height`), `coordinates` (`latitude`, `longitude`, when the article has them),
`description` (Wikidata short description), `last_modified`, `content_type`,
`last_updated`. `extract_html` is always empty.

```json
{"query": "Tour Eiffel", "language": "fr", "sentences": 5}
```

### wiki_get_page

Provide `query` (title) or `page_id`; one of them is required.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | One of `query` / `page_id` | – | Article title |
| `page_id` | integer | One of `query` / `page_id` | – | Wikipedia page ID |
| `language` | string | No | `en` | Language edition |
| `redirect` | boolean | No | `true` | Follow redirects |
| `include_images` | boolean | No | `true` | Include the article's lead image |
| `include_links` | boolean | No | `true` | Accepted, but links are not currently populated (see [Limitations](#limitations)) |
| `include_references` | boolean | No | `false` | Accepted, but references are not currently populated |

Result fields:

| Field | Description |
|-------|-------------|
| `title`, `page_id`, `url`, `language` | Article identity |
| `content` | Full plain-text article |
| `summary` | First paragraph of `content` |
| `sections` | List of `{title, level, content}` parsed from `==` headings (first entry is `Introduction`) |
| `images` | Lead image (`url`, `title`) when `include_images` is true |
| `categories` | Category names without the `Category:` prefix |
| `last_modified`, `last_modified_by`, `revision_id` | Latest revision |
| `word_count` | Words in `content` |
| `links`, `references`, `html_content` | Present for schema compatibility; currently empty |

```json
{"page_id": 5043734}
```

---

## Typical Workflow

1. `wiki_search` to find the exact title or `page_id`.
2. `wiki_get_summary` for a quick overview.
3. `wiki_get_page` only when the full text is needed (responses can be large).

Using `page_id` from step 1 avoids title ambiguity and redirect issues.

---

## Errors and Troubleshooting

Errors raised while fetching are wrapped with a tool prefix, e.g.
`Failed to get Wikipedia page: Page not found: Foo`.

| Message | Cause | Fix |
|---------|-------|-----|
| `Either 'query' or 'page_id' must be provided` | Neither identifier given | Pass one |
| `Page not found: <title>` | No such article in that language edition | Run `wiki_search` first; check `language` |
| `Wikipedia resource not found` | HTTP 404 (often a bad `language` code) | Use a valid edition code |
| `Wikipedia API request failed: HTTP <code>` | Other HTTP error, including rate limiting | Slow down and retry |
| `Wikipedia API request failed: <reason>` | Network error or timeout | Check outbound connectivity |

Disambiguation pages are returned like any other page; refine the title
(e.g. `Mercury (planet)`).

---

## Limitations

- `wiki_get_page` returns plain text only; tables, infoboxes and markup are
  flattened or dropped.
- Internal/external links and references are not extracted, regardless of
  `include_links` / `include_references`.
- Only the lead image is returned, not every image in the article.
- Content is live Wikipedia and may change between calls; verify critical facts.
- Wikipedia content is licensed CC BY-SA; attribute when reusing it.

---

## See Also

- [Google Search Tool Reference Guide](Google%20Search%20Tool%20Reference%20Guide.md)
- [Tavily Search Tool Reference Guide](Tavily%20Search%20Tool%20Reference%20Guide.md)
- [Glossary](../../../GLOSSARY.md)
- [MediaWiki Action API](https://www.mediawiki.org/wiki/API:Main_page)

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
