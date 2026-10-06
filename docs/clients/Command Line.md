# Command Line

The `sajha` command talks to a SAJHA server from a terminal: sign in, list, inspect
and call tools, render prompts, ask a question and watch the tool chain run, deploy
Studio tools, manage federation upstreams, and start the server itself, over HTTP or
over stdio for desktop MCP clients.

It is part of the client SDK (`clientsdk/sajhaclient/cli/`): MCP operations (tools,
prompts) go through `SajhaMCPSyncClient` and the official MCP SDK, which negotiates the
protocol version; everything else uses the REST API. The stdio server it launches lives
in the server package (`sajha/cli/stdio.py`); how stdio behaves at the protocol level is
in the [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md#stdio).

A walk-through is [Tutorial 15](../tutorials/TUTORIAL_15_sajha_cli_and_claude_desktop.md).

---

## 1. Install

```bash
pip install -e 'clientsdk[cli]'      # from a checkout; installs the `sajha` console script
python -m sajhaclient.cli --help     # the same, without installing the script
```

The `cli` extra pulls in the official MCP SDK (`mcp`). Without it, `health`, `login`,
`ask`, `studio`, `federation`, `config` and `completion` still work; `tools` and
`prompts` print an install hint and exit 1.

---

## 2. Where it connects, and as whom

Every setting resolves **flag, then environment, then profile, then default**:

| Setting | Flag | Environment | Default |
|---|---|---|---|
| Server URL | `--server`, `-s` | `SAJHA_URL` | `http://localhost:3002` |
| API key | `--api-key`, `-k` | `SAJHA_API_KEY` | none |
| Login token (JWT) | (stored by `sajha login`) | `SAJHA_TOKEN` | none |
| Profile | `--profile`, `-p` | `SAJHA_PROFILE` | the current profile |
| HTTP timeout (s) | `--timeout` | `SAJHA_TIMEOUT` | 30 |

An API key given as a flag or in the environment wins over a stored login.
`sajha config show` prints the effective settings and where each came from (secrets
shortened).

```bash
sajha login                          # prompts for user and password; stores a token
sajha login -u admin --password-stdin < pw.txt   # or set SAJHA_PASSWORD
sajha login --with-api-key sja_...   # store an API key instead (validated first)
sajha logout                         # forget this profile's credentials
sajha profile add prod https://sajha.example.com
sajha profile use prod
sajha profile list
sajha profile remove prod
```

Profiles and credentials live in one file, `config.json`, in `$SAJHA_CONFIG_DIR`, else
`$XDG_CONFIG_HOME/sajha`, else `~/.config/sajha`. The directory is created `0700` and
the file written atomically with mode `0600`. Without credentials the server treats the
CLI as anonymous (`mcp.anonymous.*`, no registry tools by default), so `tools list` shows
nothing and says so.

---

## 3. Commands

| Command | What it does | Uses |
|---|---|---|
| `sajha health` | Status, version, tool and prompt counts; no credentials needed | `GET /health` |
| `sajha tools list [--filter REGEX] [--group] [--names]` | Tools this identity can see; `--group` groups by provider (name prefix) | MCP `tools/list` |
| `sajha tools show NAME` | Description, arguments (type, required, enum, default), annotations, an example call | MCP `tools/list` |
| `sajha tools call NAME --arg k=v ...` | Call a tool | MCP `tools/call` |
| `sajha tools call NAME --json '{...}'` | Arguments as a JSON object (`-` reads stdin, `@file` a file) | MCP `tools/call` |
| `sajha prompts list [--filter REGEX]` | Prompts and their arguments (`?` marks optional) | MCP `prompts/list` |
| `sajha prompts get NAME --arg k=v ...` | Render a prompt | MCP `prompts/get` |
| `sajha ask "QUESTION" [--model ALIAS] [--verbose]` | Ask; the step events stream to the terminal as they happen. `--model` takes an alias or `provider/model`; `-` as the question reads stdin | `POST /api/ai/ask` (SSE) |
| `sajha studio deploy FILE.py [--name N] [--dry-run]` | Deploy a `@sajhamcptool` function (admin); `--dry-run` only analyses | `POST /admin/studio/deploy` (`/analyze`) |
| `sajha studio import-openapi URL\|FILE [--prefix P] [--base-url U] [--server-index N] [--tag T] [--method M] [--path P] [--select 'GET /path'] [--auth JSON] [--graphql] [--dry-run]` | Import an OpenAPI 3.x / Swagger 2.0 spec (or, with `--graphql`, a GraphQL endpoint or introspection file) as tools (admin): `--dry-run` lists the operations and their proposed names; otherwise every selectable operation, or each `--select`, is deployed. Credentials in `--auth` are secret references ([API Import](../architecture/API%20Import.md)) | `POST /admin/studio/api-import/parse`, `/deploy` |
| `sajha studio delete NAME` | Delete a Studio-generated tool (admin) | `POST /admin/studio/delete` |
| `sajha federation list` | Upstream MCP servers, state, approved items (admin) | `GET /api/federation/upstreams` |
| `sajha federation add --id ID --url URL ...` | Add an upstream (`--def JSON` for the whole definition) (admin) | `POST /api/federation/upstreams` |
| `sajha federation refresh ID` / `remove ID` | Reconnect and re-list / remove a run-time upstream (admin) | `/api/federation/upstreams/{id}` |
| `sajha config show [--remote]` | Effective CLI settings; `--remote`: the server's effective `ai.*` configuration (admin) | local / `GET /api/ai/config` |
| `sajha serve [--stdio]` | Run the server from a checkout (see §5) | |
| `sajha db check\|sql ...` | Database schema helper (no migrations; it changes nothing): runs `python -m sajha.db` in the server checkout (`--root` or `SAJHA_HOME` before the subcommand; the Python running `sajha` needs the server's requirements) | the database, not HTTP ([Database Setup](../getting-started/Database%20Setup.md)) |
| `sajha completion bash\|zsh\|fish` | Print a shell completion script | |
| `sajha version` (or `--version`) | Print the CLI version | |

The federation commands need a server with the federation API; on one without it they
exit 5. The server has no general "effective configuration" endpoint; `config show
--remote` covers the `ai.*` settings, the only ones it reports with their sources.

### Arguments

`--arg key=value` values are typed by the tool's input schema: a `string` property keeps
the text as given, other types are parsed as JSON (`n=3`, `flag=true`, `ids=[1,2]`), and
a value that does not parse as the declared type is a usage error. `key=@path` reads the
value from a file. `--arg` and `--json` combine; `--arg` wins on a clash. `--no-schema`
skips the schema lookup (values are JSON if they parse, else text).

### Output

Text output prints a tool's `structuredContent` (or its text blocks, as pretty JSON when
they are JSON) and tables for lists, truncated to the terminal width. `--json` (or
`-o json`) prints the full result instead; on `tools call`, `--json` with no value means
JSON output. Colour is used only on a terminal, never with `NO_COLOR` or `--no-color`.

`sajha ask` writes the steps to stderr and the answer to stdout, so
`sajha ask "..." > answer.txt` keeps only the answer:

```
  shortlist  12 tools: calc_percentage_change, ...
  model      mock/mock-planner (step 1)
  -> calc_percentage_change {"old_value": 10, "new_value": 15}
  ok   calc_percentage_change 0ms {"old_value": 10, "new_value": 15, "percentage_change": 50.0}

percentage change = 50.0 (from calc_percentage_change with old_value=10, new_value=15).

  confidence 1.0
```

When the server asks to confirm a tool call it prints the fingerprint; re-run with
`--confirm FINGERPRINT`. `--json` prints the final result, `--json --events` every event
as one JSON line. The event schema is in the
[Intelligence Layer](../architecture/Intelligence%20Layer.md) guide.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | The operation failed: the tool returned `isError`, the server refused the input, a server error |
| 2 | Usage error (bad command line or argument value) |
| 3 | Authentication required or rejected: run `sajha login` or pass `--api-key` |
| 4 | Permission denied: the identity lacks the role or tool access |
| 5 | Not found: tool, prompt, upstream or endpoint |
| 6 | Cannot reach the server |
| 130 | Interrupted |

### Shell completion

```bash
eval "$(sajha completion bash)"                               # ~/.bashrc
eval "$(sajha completion zsh)"                                # ~/.zshrc
sajha completion fish > ~/.config/fish/completions/sajha.fish
```

The scripts are generated from the command tree; tool names after `tools show|call`
complete live from the server.

---

## 4. Desktop clients (stdio)

A desktop MCP client launches SAJHA as a subprocess and speaks MCP over its stdin and
stdout. Any of these starts it:

```bash
sajha serve --stdio --user admin                 # needs the checkout: run inside it, --root, or SAJHA_HOME
python /path/to/sajhamcpserver/run_server.py --stdio --user admin
python -m sajha.cli.stdio --user admin           # with the checkout on PYTHONPATH
```

| Option | Environment | Meaning |
|---|---|---|
| `--user ID` | `SAJHA_STDIO_USER` | Act as this SAJHA user; their roles decide the tools |
| `--api-key KEY` | `SAJHA_API_KEY` | Act as this API key; its tool access list decides |
| (neither) | | Anonymous: `mcp.anonymous.*`, no registry tools by default |
| `--root DIR` | `SAJHA_HOME` | The checkout to serve from (default: the one the code is in) |
| `--config FILE` | `SAJHA_CONFIG_FILE` | YAML configuration (default `config/application.yml`) |
| `--log-level LEVEL` | `SAJHA_STDIO_LOG_LEVEL` | stderr log level (default `WARNING`) |
| `--log-file FILE` | | Also log to a file |
| `--with-ai` | | Also start the LLM gateway, so `sajha_ask` is registered when `ai.ask.mcp_tool_enabled` is on |

An unknown user or an invalid API key stops the process with exit code 2 and a message
on stderr; nothing is written to stdout. The process changes to the checkout's directory,
so relative paths in the configuration (and `SAJHA_DB_PATH`) resolve as they do for the
HTTP server. It loads only what MCP needs (database, storage, tool and prompt
registries, composite tools); the web UI, observability and, unless `--with-ai`, the LLM
gateway are not started.

Things to know:

- **One database, two processes.** The stdio process opens the same database and data
  files as an HTTP server on the same checkout. SQLite (WAL) is fine with that, but a
  DuckDB file can be held by only one process: with the HTTP server running, the DuckDB
  tools fail to open their file in the stdio process (the error goes to stderr). Point
  one of them at a different `data/` directory, or use the HTTP server instead (most
  desktop clients also accept a Streamable HTTP URL).
- **Start-up time** is dominated by loading the tool registry; set `--log-level INFO` to
  see how long it takes.

### Claude Code

```bash
claude mcp add sajha --env SAJHA_STDIO_USER=admin \
  -- /path/to/sajhamcpserver/venv/bin/python /path/to/sajhamcpserver/run_server.py --stdio
```

Add `--scope user` to make it available in every project. With an API key instead of a
user, pass `--env SAJHA_API_KEY=sja_...`. To use a running HTTP server instead of a
subprocess: `claude mcp add --transport http sajha http://localhost:3002/mcp`.

### Claude Desktop

In `claude_desktop_config.json` (Settings > Developer > Edit Config):

```json
{
  "mcpServers": {
    "sajha": {
      "command": "/path/to/sajhamcpserver/venv/bin/python",
      "args": ["/path/to/sajhamcpserver/run_server.py", "--stdio"],
      "env": { "SAJHA_STDIO_USER": "admin" }
    }
  }
}
```

Use the Python interpreter that has SAJHA's requirements installed. Restart the client
after editing; stderr from the server appears in the client's MCP log.

### Other clients

Any client that launches a stdio server takes the same `command`, `args` and `env`. The
official Python SDK, for example:

```python
from mcp import Client, StdioServerParameters

params = StdioServerParameters(command="/path/to/venv/bin/python",
                               args=["/path/to/sajhamcpserver/run_server.py", "--stdio", "--user", "admin"])
async with Client(params) as client:          # mode="auto": server/discover, 2026-07-28
    print((await client.list_tools()).tools[0].name)
```

---

## 5. Running the HTTP server

`sajha serve` without `--stdio` runs `run_server.py` from the checkout (`--host`,
`--port`, and anything after them is passed through), the same as running it directly.
