# Tutorial 15: The sajha CLI and Claude Desktop

Drive SAJHA from a terminal with the `sajha` command, then hand the same tools to a
desktop MCP client (Claude Desktop or Claude Code) that launches SAJHA over stdio. Every
command and option is in the [Command Line](../clients/Command%20Line.md) guide; how the
stdio transport behaves is in the [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md#stdio).

## What you'll learn

- How to install the CLI, sign in and keep profiles for several servers
- How to find, inspect and call a tool, and how arguments are typed
- How to watch `ask` pick and run tools from the terminal
- How to deploy a Studio tool from a file
- How to register SAJHA with Claude Code and Claude Desktop over stdio, and choose its identity

## Prerequisites

- A SAJHA checkout with its requirements installed and the server running
  ([Tutorial 1](TUTORIAL_01_getting_started.md)); this tutorial assumes `http://localhost:3002`
- The admin account (`admin` / `admin123` on a fresh database)

## Steps

### 1. Install the CLI

From the checkout:

```bash
pip install -e 'clientsdk[cli]'
sajha --version
sajha health
```

`health` needs no credentials. If the server is elsewhere, pass `--server URL` or set
`SAJHA_URL`.

### 2. Sign in

```bash
sajha login -u admin
```

The token is stored in `~/.config/sajha/config.json`, readable only by you (`0600`).
`sajha config show` prints what the CLI will use and where each value came from. For a
second server, add a profile and switch between them:

```bash
sajha profile add staging https://sajha-staging.example.com
sajha --profile staging login -u admin
sajha profile use default
```

### 3. Find and call a tool

```bash
sajha tools list --group --filter '^calc_'
sajha tools show calc_percentage_change
sajha tools call calc_percentage_change --arg old_value=10 --arg new_value=15
```

The arguments are typed from the tool's schema, so `10` arrives as a number. The same
call with a JSON object, printing the whole MCP result:

```bash
sajha tools call calc_percentage_change --json '{"old_value": 10, "new_value": 15}' -o json
```

Try a tool that does not exist and check the exit code: `echo $?` prints `5` (not found).
Scripts can rely on the exit codes listed in the guide.

### 4. Ask

```bash
sajha ask "what is the percentage change from 10 to 15"
```

The shortlist, the model step, each tool call and its result appear as they happen, then
the answer and its confidence. The steps go to stderr, so `sajha ask "..." > answer.txt`
saves only the answer. With no LLM provider configured the built-in mock model answers
([Tutorial 10](TUTORIAL_10_ask_sajha.md)).

### 5. Deploy a Studio tool from a file

Save this as `add_numbers.py`:

```python
from sajha.studio import sajhamcptool

@sajhamcptool(description="Add two numbers", category="Demo")
def add_numbers(a: int, b: int) -> dict:
    return {"sum": a + b}
```

```bash
sajha studio deploy add_numbers.py --dry-run    # analyse only
sajha studio deploy add_numbers.py
sajha tools call add_numbers --arg a=2 --arg b=3
sajha studio delete add_numbers
```

The tool name defaults to the file name (`--name` overrides it). Deploying needs an
admin login.

### 6. Add SAJHA to Claude Code over stdio

A desktop client starts its own SAJHA process and talks MCP over stdin/stdout. First
check it by hand: this prints one JSON line (the `server/discover` result) and exits.

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}' \
  | python run_server.py --stdio --user admin 2>/dev/null
```

Now register it (use absolute paths and the Python that has SAJHA's requirements):

```bash
claude mcp add sajha --env SAJHA_STDIO_USER=admin \
  -- "$(which python)" "$PWD/run_server.py" --stdio
claude mcp list
```

Start `claude` and ask it to use a SAJHA tool, for example "use calc_percentage_change
for 10 to 15".

### 7. Add SAJHA to Claude Desktop

Open Settings > Developer > Edit Config and add:

```json
{
  "mcpServers": {
    "sajha": {
      "command": "/path/to/python",
      "args": ["/path/to/sajhamcpserver/run_server.py", "--stdio"],
      "env": { "SAJHA_STDIO_USER": "admin" }
    }
  }
}
```

Restart Claude Desktop; SAJHA's tools appear in the tools menu.

### 8. Choose the identity

The stdio process acts as one caller, mapped through SAJHA's access control:

- `SAJHA_STDIO_USER=<user>`: that user's roles decide the tools. `admin` sees everything;
  use a less privileged user for day-to-day work.
- `SAJHA_API_KEY=sja_...`: an API key's tool access list decides, so you can hand a
  desktop client exactly the tools you want (create the key in Admin > API Keys with an
  allowlist such as `calc_*`).
- Neither: anonymous, which sees no registry tools by default.

## What you learned

- `sajha` signs in once per profile and keeps the token private
- `tools list|show|call` work over MCP with schema-typed arguments and meaningful exit codes
- `ask` streams the tool chain to the terminal
- `studio deploy` publishes a tool from a file
- `run_server.py --stdio` (or `sajha serve --stdio`) serves MCP to desktop clients, as
  the user or API key you choose

## What next

- [Command Line](../clients/Command%20Line.md): every command, option and exit code
- [Client SDK Guide](../clients/Client%20SDK%20Guide.md): the same operations from Python
- Next tutorial: [Metrics, Costs and Alerts](TUTORIAL_16_metrics_costs_and_alerts.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
