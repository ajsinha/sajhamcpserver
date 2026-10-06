# MCP Apps and Headers Guide

Two optional pieces of tool metadata that only 2026-07-28 clients use: **MCP Apps**,
which attach an interactive HTML view to a tool, and **`x-mcp-header`**, which mirrors
a tool argument into an HTTP header so proxies and gateways can route on it. Both are
set in a tool's JSON config under `config/tools/`. Legacy (2025-11-25) responses are
unchanged by either. Background on the two protocol eras is in the
[MCP Protocol Guide](MCP%20Protocol%20Guide.md); conformance details are in
[MCP 2026-07-28 Compliance §4.2–4.3](MCP%202026-07-28%20Compliance.md).

---

## 1. MCP Apps (`io.modelcontextprotocol/ui`)

### What the client sees

With `mcp.apps.enabled: true` (the default):

- `server/discover` advertises `capabilities.extensions["io.modelcontextprotocol/ui"]`.
- A tool that binds a view carries `_meta.ui` in modern `tools/list`.
- `resources/list` lists every view as a `ui://sajha/...` resource, and
  `resources/read` returns it with MIME type `text/html;profile=mcp-app`.
- The host renders the view in a sandboxed iframe and passes it the tool result. A
  client without Apps support ignores all of this and shows the normal text and
  `structuredContent` result.

### Bind a view to a tool

```json
{
  "name": "calc_loan_amortization",
  "implementation": "...",
  "inputSchema": { ... },
  "outputSchema": { ... },
  "_meta": { "ui": { "resourceUri": "ui://sajha/loan-amortization.html" } }
}
```

Optional: `"visibility": ["model", "app"]` (a non-empty list of those two values).
An invalid `_meta.ui` (a URI that is not `ui://`, names no available view, or a bad
`visibility`) is ignored with one warning in the log, and the tool is still listed.

### Where views come from

| Source | Published as |
|---|---|
| Bundled views in `sajha/core/mcp_app_views/*.html` | `ui://sajha/<file name with "_" replaced by "-">` |
| Your views: `*.html` in `mcp.apps.dir` (default `config/apps`; the directory does not exist until you create it) | same rule |

So `config/apps/fx_chart.html` becomes `ui://sajha/fx-chart.html`. Views are read
from the local filesystem (not the storage backend), symlinks are skipped, and a view
larger than 2 MB is refused.

### Writing a view

A view must be **self-contained**: inline its scripts, styles and data. SAJHA declares
no CSP domains for views, so hosts block all network access from them. It talks to
the host through the MCP Apps `postMessage` protocol (`ui/initialize`,
`ui/notifications/tool-result`, host-context and size-change notifications). The
bundled `loan_amortization.html` is a complete working example: it draws a
principal/interest chart and a schedule table from the tool's `yearly_schedule`
output, and follows the host's theme.

Implementation: `sajha/core/mcp_apps.py`. Tests: `tests/test_mcp_apps.py`.

---

## 2. `x-mcp-header`: arguments as HTTP headers

### What it does

Annotate an input property with a header token:

```json
"inputSchema": {
  "type": "object",
  "properties": {
    "symbol": { "type": "string", "x-mcp-header": "Symbol" }
  },
  "required": ["symbol"]
}
```

A 2026-07-28 client calling this tool must then send the argument's value twice: in
the JSON body and as the header `Mcp-Param-Symbol: AAPL` (non-ASCII values use the
`=?base64?…?=` form). Infrastructure in front of SAJHA can route, rate-limit or log on
that header without parsing JSON.

SAJHA enforces agreement: a missing, extra or different `Mcp-Param-*` header, or
malformed base64, is rejected with `-32020` (HTTP 400). For example, calling
`yahoo_get_quote` without the header answers *"Header mismatch: Mcp-Param-Symbol header
is missing but the body's 'symbol' argument is present"*. Legacy clients are not
affected.

The stock-quote tools annotate `symbol` this way (`symbol` → `Mcp-Param-Symbol`). The
current list is whatever the configs say: `grep -l x-mcp-header config/tools/*.json`.

### Rules, and what happens when they are broken

An annotation is valid only when it:

- sits on a property reached from the schema root through `properties` only;
- is an RFC 9110 token (letters, digits and ``!#$%&'*+-.^_`|~``);
- is on a `string`, `integer` or `boolean` property (not `number`, object or array);
- is unique across the schema, ignoring case.

The specification makes clients drop a **whole tool** whose annotations are invalid.
To keep a misconfigured tool usable, SAJHA removes each invalid annotation when the
schema is loaded and logs one warning per tool and problem; the argument is then
simply not mirrored into a header. Implementation:
`sanitize_x_mcp_headers()` in `sajha/core/mcp_modern.py`, applied by
`BaseMCPTool.input_schema`.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
