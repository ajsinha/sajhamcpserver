# External MCP server templates

Templates for `config/mcp_servers.json`, the file where a SAJHA instance lists the MCP servers it
proxies (embeds and proxies calls to; the console page is Proxied MCP servers). The format is the `mcpServers` JSON used by Claude Desktop, Cursor and VS Code, so a block
from any of them can be pasted in unchanged. Copy a template, keep what you need, and set the
environment variables it names. `config/mcp_servers.json` itself is git-ignored because it may hold
credentials; these `.example` files are tracked and hold none.

The file's keys, the loader and how embedded servers behave are documented in
[Federation](../../docs/architecture/Federation.md); how their tools reach other SAJHA servers is in
[SAJHA Net](../../docs/architecture/SAJHA%20Net.md) ("Vendors and external servers").

| Template | Shows |
|---|---|
| `01_local_stdio_npx.json.example` | Reference servers over stdio with `npx`; a tool filter that exposes only read-only tools; `env`; a vendor and prefix of your own |
| `02_local_stdio_uvx.json.example` | Python servers over stdio with `uvx`; an absolute command path; `cwd`; arguments |
| `03_docker_stdio.json.example` | A container over stdio with `docker run -i`; a token passed by name from the environment |
| `04_remote_bearer_token.json.example` | Hosted servers over Streamable HTTP with a bearer or API-key header; `${NAME}` and `${NAME:default}`; two entries of one vendor with different prefixes |
| `05_remote_no_auth.json.example` | Hosted servers that need no credential |
| `06_remote_oauth_sign_in.json.example` | Hosted servers that need each user to sign in with OAuth: not supported yet, kept disabled as templates |
| `07_legacy_sse.json.example` | The legacy HTTP+SSE transport (`"type": "sse"`) |
| `08_internal_not_external.json.example` | `"external": false`: your own teams' servers, and another SAJHA, governed as internal federation upstreams |
| `09_mixed_complete.json.example` | All of the above in one file, as a starting point |

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
| `cwd` | | stdio only: the working directory |

Keys whose names start with `_` are comments and are ignored.

## Before you use one

- Server packages, URLs and arguments change; check each against its maintainer's documentation.
- stdio servers run as processes of SAJHA and need `federation.allow_stdio: true`; run only code you
  would run on that machine yourself, and pin commands to absolute paths in production.
- Prefer `${NAME}` references over raw secrets. A raw secret works (SAJHA shows a notice), but then
  treat `config/mcp_servers.json` like a password file.
- Narrow what you expose with `tools`; most servers include tools that write or delete.
