# MSDOC Search Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Setup](#setup)
3. [Calling the Tools](#calling-the-tools)
4. [Tools](#tools)
   - [msdoc_list_files](#msdoc_list_files)
   - [msdoc_read_word](#msdoc_read_word)
   - [msdoc_search_word](#msdoc_search_word)
   - [msdoc_get_word_metadata](#msdoc_get_word_metadata)
   - [msdoc_read_excel](#msdoc_read_excel)
   - [msdoc_read_excel_sheet](#msdoc_read_excel_sheet)
   - [msdoc_get_excel_sheets](#msdoc_get_excel_sheets)
   - [msdoc_search_excel](#msdoc_search_excel)
   - [msdoc_get_excel_metadata](#msdoc_get_excel_metadata)
   - [msdoc_extract_text](#msdoc_extract_text)
5. [Typical Workflow](#typical-workflow)
6. [Errors and Troubleshooting](#errors-and-troubleshooting)
7. [Limitations](#limitations)
8. [See Also](#see-also)

---

## Overview

The MSDOC tools read Microsoft Word and Excel files that sit in a local
documents directory on the SAJHA server. They list, read, search and extract
metadata; they never modify files and make no network calls.

| Tool | File type | Purpose |
|------|-----------|---------|
| `msdoc_list_files` | both | List documents in the directory |
| `msdoc_read_word` | Word | Paragraphs and tables |
| `msdoc_search_word` | Word | Paragraphs containing a term |
| `msdoc_get_word_metadata` | Word | Core document properties |
| `msdoc_read_excel` | Excel | Rows from a sheet, optionally with formulas |
| `msdoc_read_excel_sheet` | Excel | Rows from a sheet chosen by name or index |
| `msdoc_get_excel_sheets` | Excel | Sheet names and indexes |
| `msdoc_search_excel` | Excel | Cells containing a term |
| `msdoc_get_excel_metadata` | Excel | Workbook properties |
| `msdoc_extract_text` | both | All text as one plain-text string |

Implementation: `sajha.tools.impl.msdoc_tools_tool_refactored`; tool configs:
`config/tools/msdoc_*.json`.

---

## Setup

- **Libraries:** `python-docx` (Word) and `openpyxl` (Excel). If one is
  missing the affected tools fail with a message naming the package to install.
- **Documents directory:** `data/msdocs` (relative to the server's working
  directory). It is the default for every MSDOC tool and is set explicitly as
  `"docs_directory": "data/msdocs"` in `config/tools/msdoc_list_files.json`;
  add the same key to another tool's config to point it elsewhere. The
  directory is created if it does not exist.
- **Credentials:** none. Access to the tools is governed by normal SAJHA user
  and API-key permissions; document contents never leave the server except in
  tool results.

Copy `.docx` / `.xlsx` files into the directory and refer to them by bare file
name (e.g. `report.docx`). See the
[Configuration Reference](../../getting-started/Configuration%20Reference.md)
for general configuration.

---

## Calling the Tools

Over MCP, `POST /mcp` with a JSON-RPC `tools/call` (`Mcp-Session-Id` optional):

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call",
 "params": {"name": "msdoc_read_word", "arguments": {"filename": "report.docx"}}}
```

Over REST, `POST /api/tools/execute`:

```json
{"tool": "msdoc_read_word", "arguments": {"filename": "report.docx"}}
```

which returns `{"success": true, "result": {...}}`. Authenticate with
`Authorization: Bearer <token>` or `X-API-Key: <key>`. See the
[MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol
details.

---

## Tools

### msdoc_list_files

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_type` | string | No | `all` | `all`, `word` (`.docx`, `.doc`) or `excel` (`.xlsx`, `.xls`, `.xlsm`) |

Result: `directory`, `file_type`, `count`, and `files` — each with `filename`,
`path`, `extension`, `size` (bytes) and `modified` (Unix timestamp), newest
first.

### msdoc_read_word

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Word file name (`.docx`) |

Result: `filename`, `paragraphs` (non-empty paragraph strings),
`paragraph_count`, `tables` (each a list of rows, each row a list of cell
strings), `table_count`.

### msdoc_search_word

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Word file name |
| `search_term` | string | Yes | Case-insensitive substring |

Result: `filename`, `search_term`, `match_count`, and `matches` — each
`{paragraph_index, text}`. Only paragraphs are searched, not tables.

### msdoc_get_word_metadata

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Word file name |

Result: `filename` and `metadata` with `author`, `title`, `subject`, `created`,
`modified`.

### msdoc_read_excel

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `filename` | string | Yes | – | Excel file name (`.xlsx`) |
| `sheet_name` | string | No | – | Sheet to read |
| `sheet_index` | integer | No | – | 0-based sheet index (used if `sheet_name` is not given) |
| `max_rows` | integer | No | `100` | 1–10,000 |
| `include_formulas` | boolean | No | `false` | Return formulas instead of cached values, plus a `formulas` list |

With neither `sheet_name` nor `sheet_index`, the active sheet is read.

Result: `filename`, `sheet_name`, `data` (list of rows, each a list of cell
values), `row_count`, `column_count`, and — when `include_formulas` is true —
`formulas`: per row, a list of `{cell, formula}` (e.g. `{"cell": "C2", "formula": "=A2*B2"}`).

### msdoc_read_excel_sheet

Same as `msdoc_read_excel` without formula support.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `filename` | string | Yes | – | Excel file name |
| `sheet_name` | string | No | – | Sheet name |
| `sheet_index` | integer | No | – | 0-based sheet index |
| `max_rows` | integer | No | `100` | 1–10,000 |

### msdoc_get_excel_sheets

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Excel file name |

Result: `filename`, `count`, and `sheets` — each `{index, name}`.

### msdoc_search_excel

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Excel file name |
| `search_term` | string | Yes | Case-insensitive substring |
| `sheet_name` | string | No | Sheet to search (default: the active sheet) |

Searches up to 10,000 rows of one sheet. Result: `filename`, `sheet_name`,
`search_term`, `match_count`, and `matches` — each
`{row_index, column_index, value}` (0-based).

### msdoc_get_excel_metadata

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Excel file name |

Result: `filename` and `metadata` with `creator`, `title`, `subject`,
`created`, `modified`.

### msdoc_extract_text

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | string | Yes | Word or Excel file name |

Word: paragraphs joined by newlines. Excel: the active sheet (up to 10,000
rows), cells tab-separated, rows newline-separated. Result: `filename`,
`text`, `character_count`.

---

## Typical Workflow

| Step | Tool | Arguments |
|------|------|-----------|
| 1 | `msdoc_list_files` | `{"file_type": "excel"}` |
| 2 | `msdoc_get_excel_sheets` | `{"filename": "sales.xlsx"}` |
| 3 | `msdoc_read_excel_sheet` | `{"filename": "sales.xlsx", "sheet_name": "Q4", "max_rows": 500}` |
| 4 | `msdoc_search_excel` | `{"filename": "sales.xlsx", "search_term": "widget", "sheet_name": "Q4"}` |

For Word: `msdoc_list_files` → `msdoc_search_word` to locate content →
`msdoc_read_word` for the full document.

---

## Errors and Troubleshooting

| Message | Cause | Fix |
|---------|-------|-----|
| `File not found: <name>` | Not in the documents directory | Run `msdoc_list_files`; use the exact name including extension |
| `python-docx library not installed ...` | Missing dependency | `pip install python-docx` |
| `openpyxl library not installed ...` | Missing dependency | `pip install openpyxl` |
| `Failed to read Word document: ...` | Corrupt file or legacy `.doc` | Re-save as `.docx` |
| `Failed to read Excel document: ...` | Bad `sheet_name` / `sheet_index`, corrupt file, or legacy `.xls` | Check names with `msdoc_get_excel_sheets`; re-save as `.xlsx` |
| `Unsupported file type: <ext>` | `msdoc_extract_text` on a non-Office file | Use Word or Excel files |

An empty `files` list from `msdoc_list_files` means the directory is empty or
unreadable by the server process.

---

## Limitations

- **Formats:** `.doc`, `.xls` and `.xlsm` appear in listings, but the
  underlying libraries only read `.docx` and `.xlsx`/`.xlsm` reliably; legacy
  binary `.doc` / `.xls` files fail to open.
- **Word:** headers, footers, comments, tracked changes and embedded objects
  are not extracted; formatting is discarded.
- **Excel:** charts, images and pivot-table definitions are not read; cell
  values come from the last saved calculation (formulas are not recalculated).
- **Search:** case-insensitive substring only — no regex, fuzzy matching,
  ranking or multi-file search.
- **Size:** whole workbooks/documents are loaded into memory; very large
  files are slow. Use `max_rows` and sheet selection to limit output.
- **Single directory:** only files directly inside the documents directory
  are listed (no sub-folders). Pass bare file names only.

---

## See Also

- [SQL Select Tool Reference Guide](../analytics/SQL%20Select%20Tool%20Reference%20Guide.md) — SQL over CSV/tabular files
- [Glossary](../../../GLOSSARY.md)

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
