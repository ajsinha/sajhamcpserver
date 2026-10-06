# Connected Account Tools Reference Guide

These tools call a third-party service **as the signed-in user**, through the account that
user linked on `/account/connections`. Each declares
`"auth": {"connected_account": "<provider>", "scopes": [...]}` in its config; SAJHA binds the
caller's token to the call, refreshes it when needed, and asks the user to connect when there
is no usable link. Design, providers and security:
[Connected Accounts](../../architecture/Connected%20Accounts.md).

A tool is listed (`tools/list`, the Tools page, Ask SAJHA) only while its provider is
configured: an administrator registers an OAuth app with the service and sets
`accounts.providers.<id>.client_id` and `client_secret_ref`.

| Tool | Provider | Scopes it needs | Class | What it does |
|---|---|---|---|---|
| `github_list_my_repos` | `github` | none (private repositories need `repo`) | `sajha.accounts.tools.github.GithubListMyReposTool` | The user's repositories: owned, collaborator, organization |
| `github_create_issue` | `github` | `repo` | `sajha.accounts.tools.github.GithubCreateIssueTool` | Opens an issue as the user (`destructiveHint`) |
| `slack_post_message` | `slack` | `chat:write` | `sajha.accounts.tools.slack.SlackPostMessageTool` | Posts to a channel, a DM or a thread as the user (`destructiveHint`) |
| `google_drive_search` | `google` | `https://www.googleapis.com/auth/drive.readonly` | `sajha.accounts.tools.google.GoogleDriveSearchTool` | Full-text search of the user's Drive and shared drives |
| `ms365_list_my_events` | `microsoft` | `Calendars.Read` | `sajha.accounts.tools.microsoft.MS365ListMyEventsTool` | The user's Outlook calendar events in a window (UTC) |
| `connected_http_request` | `github` (as shipped) | none | `sajha.accounts.tools.http_request.ConnectedHttpRequestTool` | Read-only GitHub REST calls under bound paths |

The configs are in `config/tools/` under the tool names; the schemas there are the contract
and every call is validated against them.

## The APIs behind them

* GitHub REST API v3: `GET /user/repos`, `POST /repos/{owner}/{repo}/issues`.
* Slack Web API: `chat.postMessage` (Slack answers HTTP 200 with `ok: false` on errors;
  `invalid_auth`, `token_revoked` and `token_expired` count as a rejected token).
* Google Drive API v3: `files.list` with a `fullText contains '...' and trashed = false`
  query (quotes escaped), newest first.
* Microsoft Graph v1.0: `GET /me/calendarView` with `Prefer: outlook.timezone="UTC"`.

## When the user has not connected

| Caller | What happens |
|---|---|
| MCP client with URL elicitation | it is asked to open the connect page, then the call is retried (MCP 2026-07-28: MRTR; 2025-11-25: error `-32042`) |
| Other MCP clients | `isError: true` with the connect URL in the text |
| `POST /api/tools/execute` | HTTP 428 with `connect_url` |
| Ask SAJHA | a **Connect GitHub** (or Slack, ...) button, then ask again |

An API key or an anonymous caller has no connected accounts; the error says so.

## Binding another endpoint: `connected_http_request`

The implementation reads its binding from the tool config:

```json
"auth": {"connected_account": "github", "scopes": []},
"http": {"base_url": "https://api.github.com",
         "methods": ["GET"],
         "paths": ["/user", "/user/*", "/repos/*", "/search/*"],
         "headers": {}}
```

To bind another service, copy `config/tools/connected_http_request.json` under a new
name, change `auth.connected_account`, `http.base_url` (a host in that provider's
`api_hosts`), the allowed `methods` and the `paths` (fnmatch patterns), and the input
schema's `method` enum. Paths with `..`, `//` or a scheme are refused, as is any host
outside the provider's `api_hosts`. A binding that allows `POST`, `PATCH` or `DELETE` must
set `annotations.destructiveHint: true`.

## Writing your own

Subclass `sajha.accounts.tools.base.ConnectedAccountTool`, set `default_provider` (and
`default_scopes`), implement `run(arguments)` and call the API with `self.api_json(method,
url, params=..., json_body=...)`; `self.token()` is the bound token (its `connection` has
the account name and scopes). Any other tool can declare `auth.connected_account` in its
config and read `sajha.accounts.current_token("<provider>")`. Results of such tools are
never cached.
