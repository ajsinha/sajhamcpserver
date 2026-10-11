# External MCP server templates

Templates for `config/mcp_servers.json`, the file where a SAJHA instance lists the MCP servers it
proxies (embeds and proxies calls to; the console page is Proxied MCP servers). The format is the `mcpServers` JSON used by Claude Desktop, Cursor and VS Code, so a block
from any of them can be pasted in unchanged. Copy a template, keep what you need, and set the
environment variables it names. `config/mcp_servers.json` itself is git-ignored because it may hold
credentials; these `.example` files are tracked and hold none.

The file's keys, the loader and how embedded servers behave are documented in
[Federation](../../docs/architecture/Federation.md#the-mcpservers-file); how their tools reach other
SAJHA servers is in [SAJHA Net](../../docs/architecture/SAJHA%20Net.md#56-vendors-and-external-servers)
§5.6 (an external server is offered into this server's nets under its prefix, and is never a member).

| Template | Shows |
|---|---|
| `01_local_stdio_npx.json.example` | Reference servers over stdio with `npx`; a tool filter that exposes only read-only tools; `env`; a vendor and prefix of your own |
| `02_local_stdio_uvx.json.example` | Python servers over stdio with `uvx`; an absolute command path; `cwd`; arguments |
| `03_docker_stdio.json.example` | A container over stdio with `docker run -i`; a token passed by name from the environment |
| `04_remote_bearer_token.json.example` | Hosted servers over Streamable HTTP with a bearer or API-key header; `${NAME}` and `${NAME:default}`; two entries of one vendor with different prefixes |
| `05_remote_no_auth.json.example` | Hosted servers that need no credential |
| `06_remote_oauth_sign_in.json.example` | Hosted servers that ask each user to sign in with OAuth (`"auth": {"type": "oauth_user"}`), discovered and registered dynamically; kept disabled until you check each URL |
| `07_legacy_sse.json.example` | The legacy HTTP+SSE transport (`"type": "sse"`) |
| `08_internal_not_external.json.example` | `"external": false`: your own teams' servers, and another SAJHA, governed as internal federation upstreams |
| `09_mixed_complete.json.example` | All of the above in one file, as a starting point |
| `11_github_token_user.json.example` | GitHub's remote server called as each user with their own personal access token (`"auth": {"type": "token_user"}`): a header format, a label, where to create a token, a token pattern |
| `12_atlassian_datacenter_token_user.json.example` | A self-hosted Jira and Confluence Data Center MCP server with each user's own personal access token, as internal upstreams |
| `13_atlassian_cloud_oauth.json.example` | Atlassian's remote server for Jira and Confluence Cloud with each user's own Atlassian sign-in (`oauth_user`, dynamic client registration) |
| `14_github_oauth.json.example` | GitHub's remote server with each user's GitHub sign-in through an OAuth app your organisation registers (`client_id`, `client_secret_ref`), read scopes by default and `repo` only for users who allow changes |
| `15_google_workspace_oauth.json.example` | Google Drive and Calendar with each user's Google sign-in through an OAuth client in your Google Cloud project; Gmail noted as needing an approval rule for sending; disabled until you set the server's URL |

## Keys

Standard keys: `url`, `headers`, `command`, `args`, `env`, `type` (`http`, `sse` or `stdio`; a
`command` means stdio, a `url` means Streamable HTTP unless `type` says `sse`).

SAJHA keys, all optional:

| Key | Default | Meaning |
|---|---|---|
| `vendor` | the entry's name, lowercased, with any character other than letters, digits and `_` turned into `_` (`foo-bar` → `foo_bar`) | The organisation that answers for the server's tools |
| `prefix` | the vendor | The name its tools are published under: `<prefix>__<tool>` |
| `external` | `true` | `true`: an external server, embedded and proxied by this SAJHA, never a member of the net. `false`: an ordinary internal federation upstream |
| `tools` | all | Glob patterns of the tools to expose; anything else is not offered |
| `enabled` | `true` | `false` keeps the entry in the file without connecting to it |
| `disabled` | `false` | `true` is the same as `"enabled": false` (as some clients write it) |
| `cwd` | | stdio only: the working directory |
| `title` | the entry's name | A display name |
| `timeout_seconds` | `federation.default_timeout_seconds` | One call's deadline |
| `auth` | `"static"` | Who the vendor sees. `"static"`: one shared identity (the `headers`). `{"type": "token_user", ...}`: each user, with a personal token they save once on Server connections. `{"type": "oauth_user", ...}` (or just `"oauth_user"`): each user, after signing in at the vendor once on Server connections ([Per-User Sign-In for Proxied Servers](../../docs/architecture/Per-User%20Sign-In%20for%20Proxied%20Servers.md); keys in [Federation](../../docs/architecture/Federation.md#per-user-oauth-sign-in-oauth_user)). In `auth`, `client_id` may be `${NAME}` |

`description` is accepted and ignored. Keys whose names start with `_` are comments and are ignored, at any depth; any other key is an error
for that entry (the rest of the file still loads).

## Before you use one

- Server packages, URLs and arguments change; check each against its maintainer's documentation.
- stdio servers run as processes of SAJHA and need `federation.allow_stdio: true`; run only code you
  would run on that machine yourself, and pin commands to absolute paths in production.
- Prefer `${NAME}` references over raw secrets. A raw secret works (SAJHA shows a notice), but then
  treat `config/mcp_servers.json` like a password file.
- Narrow what you expose with `tools`; most servers include tools that write or delete.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
