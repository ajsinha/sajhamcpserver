# SharePoint Tool Reference Guide

The SharePoint tools work on one SharePoint Online site through
[Microsoft Graph](https://learn.microsoft.com/graph/api/resources/sharepoint)
(`https://graph.microsoft.com/v1.0`): documents in the site's default document library,
lists and list items, and search. They are configured tools, distinct from the tools the
[MCP Studio SharePoint creator](../../studio/MCP%20Studio%20SharePoint%20Tool%20Creator%20Guide.md)
generates (which use the same implementation).

| Tool | Class (`sajha/tools/impl/sharepoint_tool.py`) | What it does |
|---|---|---|
| `sharepoint_documents` | `SharePointDocumentTool` | Files and folders: list, read, download, upload, search, metadata, check-out/in, versions, delete, move, copy |
| `sharepoint_lists` | `SharePointListTool` | Lists and list items: read, create, update, delete, columns, OData queries |
| `sharepoint_search` | `SharePointSearchTool` | Search within the site (everything, documents or sites) or people in the directory |

The configs are `config/tools/sharepoint_documents.json`, `sharepoint_lists.json` and
`sharepoint_search.json`; the schemas there are the contract, and the server validates every
call against them (open a tool's schema page in the console for the live version).
`SharePointSiteTool` (site information, subsites, users, permissions, content types) has no
shipped config; the Studio creator generates one.

## Configuration

Each config names its site and credentials with `${...}` references, resolved by the tools
registry from `config/application.yml`, whose `sharepoint.*` and `azure.tenant.id` keys are
empty by default and read the environment (see the
[Configuration Reference](../../getting-started/Configuration%20Reference.md)):

| Reference | Environment variable | Meaning |
|---|---|---|
| `${sharepoint.site.url}` | `SHAREPOINT_SITE_URL` | The site, e.g. `https://contoso.sharepoint.com/sites/team` |
| `${azure.tenant.id}` | `AZURE_TENANT_ID` | The Entra ID (Azure AD) tenant of the app registration |
| `${sharepoint.client.id}` | `SHAREPOINT_CLIENT_ID` | The app registration (client-credentials grant) |
| `${sharepoint.client.secret}` | `SHAREPOINT_CLIENT_SECRET` | Its client secret |

Until they are set, every call answers `{"success": false, "error": "SharePoint is not
configured: ..."}` without a network request.

The app registration needs Microsoft Graph **application** permissions:
`Sites.Read.All` for reading, `Sites.ReadWrite.All` for uploads, metadata and list writes (or
`Sites.Selected` with a grant on this one site), and `User.Read.All` for people search. The
token is requested for `https://graph.microsoft.com/.default`, cached, and renewed a minute
before it expires. Only the `client_credentials` grant is implemented; another
`authentication.type` is refused with a clear error.

`sharepoint_search` takes an optional `search_region` in its config (e.g. `NAM`, `EUR`):
Graph requires a region for SharePoint searches made with application permissions in some
tenants.

## Tools

### sharepoint_documents

`operation` (required) is one of `list_files`, `get_file`, `download`, `upload`, `search`,
`get_metadata`, `update_metadata`, `check_out`, `check_in`, `get_versions`, `delete`,
`move`, `copy`.

Paths are inside the site's default document library and may be written library-relative
(`/Project/plan.docx`) or SharePoint server-relative
(`/sites/team/Shared Documents/Project/plan.docx`); the site path and a leading
`Shared Documents` or `Documents` segment are dropped, and `..` is refused. Other arguments:
`folder_path`, `file_url`, `source_url` (move, copy; `file_url` works too),
`destination_url` (the new file path), `file_name` and `content_base64` (upload, up to 4 MB),
`query` and `file_types` (search), `metadata` (update_metadata: column values),
`comment` and `publish` (check_in), `recycle` (delete; `false` deletes permanently),
`return_content` (download), `overwrite` (upload, move, copy; default false),
`recursive` (list_files; at most 1000 items, `truncated` says when there were more).
`copy` is asynchronous in Graph: it answers `status: "accepted"` with a `monitor_url`.

```json
{"operation": "list_files", "folder_path": "/Shared Documents"}
```

### sharepoint_lists

`operation` (required) is one of `get_lists`, `get_list_items`, `get_item`, `create_item`,
`update_item`, `delete_item`, `get_list_schema`, `query_items`. Other arguments:
`list_name` (title or id), `item_id`, `item_data` (create, update: column values),
`filter` (an OData `$filter`; Graph addresses columns as `fields/<Column>`),
`select_fields`, `order_by` (e.g. `fields/Created desc`), `top` (default 100, at most 5000),
`skip` (default 0). Filters and ordering on columns that are not indexed are sent with
Graph's `Prefer: HonorNonIndexedQueriesWarningMayFailRandomly`. `delete_item` sends the item
to the site recycle bin.

```json
{"operation": "query_items", "list_name": "Projects", "filter": "fields/Status eq 'Active'"}
```

### sharepoint_search

`query` (required), `search_type` (`all` by default, `documents`, `people` or `sites`),
`file_types` (e.g. `["docx", "pdf"]`), `max_results` (default 50, at most 500), `start_row`
(default 0). Searches other than `people` use Graph's `POST /search/query` limited to the
configured site (`path:"<site_url>"`); `people` searches the directory (`GET /users`).

```json
{"query": "budget", "search_type": "documents", "file_types": ["xlsx", "pdf"]}
```

## Results and errors

A successful call returns the operation's data with `success: true` and
`execution_time_ms`. A failure is returned, not raised: `{"success": false, "error": "..."}`,
with Graph's own message when Graph refused the call. Arguments that do not match the
schema are refused before the tool runs (see "Argument validation" in the
[MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md)).

Values are never pasted into URLs unescaped: paths and list names are URL-encoded and the
document search text is an OData string literal with `'` doubled.

## Known issues

- Uploads use Graph's simple upload, so files are limited to 4 MB (no upload session).
- `SharePointSiteTool`'s `get_groups` answers with an error: SharePoint site groups have no
  Microsoft Graph API.
- Only the `client_credentials` grant is implemented (no certificate credential).

## See also

- [MCP Studio SharePoint Tool Creator Guide](../../studio/MCP%20Studio%20SharePoint%20Tool%20Creator%20Guide.md)
- [Security Model](../../security/Security%20Model.md) for keeping the client secret out of tracked files

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
