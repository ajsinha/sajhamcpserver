# Tutorial 14: Sandboxed Studio Tools

Deploy a Python code tool and a script tool from MCP Studio, call them over MCP, and watch
the sandbox stop them reading the server's configuration and secrets. Then grant one of
them network access the right way. The design behind this is in
[Sandbox](../architecture/Sandbox.md).

## What you'll learn

- Which sandbox backend your server uses and what it enforces on your host
- That a Studio tool cannot read `config/`, the server's environment or the network
- How to grant a tool more (network hosts, memory, a secret) in its `sandbox` block
- How to switch backends (`bwrap`, `docker`)

## Prerequisites

- A running server you can sign in to as an administrator ([Tutorial 1](TUTORIAL_01_getting_started.md))
- `curl` and Python 3 on the command line
- Linux for the full set of guarantees; on macOS and Windows the sandbox gives a clean
  environment and limits only (step 1 shows what you have)

The commands assume the server on `http://localhost:3002`; change the port to yours.

## Steps

### 1. See what the sandbox enforces here

Sign in for a token, then ask for the sandbox status:

```bash
TOKEN=$(curl -s -X POST localhost:3002/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","password":"<your password>"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s localhost:3002/api/sandbox/status -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

`active_backend` is the backend in use (`subprocess` by default), `backends` says which
others this host has, and `guarantees` lists each guarantee with `enforced` and how. The
list comes from a live probe, so a missing kernel feature shows up as `"enforced": false`
rather than being assumed.

### 2. Deploy a Python code tool that tries to snoop

Open **MCP Studio** (`/studio`) and scroll to the Python Code Tool Creator. The
**Runs in the sandbox** panel above the editor shows the policy a new tool gets and what
the backend enforces. Paste this, name it `peek`, and press **Analyze** then **Deploy**:

```python
from sajha.studio import sajhamcptool

@sajhamcptool(description="Read a file and report the environment", category="Test")
def peek(path: str) -> dict:
    import os
    try:
        content = open(path).read()[:80]
    except Exception as e:
        content = "BLOCKED: " + type(e).__name__
    return {"content": content, "jwt_in_env": "SAJHA_JWT_SECRET" in os.environ,
            "env": sorted(os.environ), "cwd": os.getcwd()}
```

(From the command line, `POST /admin/studio/deploy` with `{"tool_name": "peek", "code": "..."}` does the same.)

### 3. Call it over MCP

Point it at the server's own configuration file (use your checkout's absolute path):

```bash
curl -s -X POST localhost:3002/mcp -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"peek","arguments":{"path":"/path/to/sajhamcpserver/config/application.yml"}}}'
```

On Linux the result says `"content": "BLOCKED: PermissionError"`, `"jwt_in_env": false`,
an environment of a dozen harmless variables (`PATH`, `HOME`, `LANG`, ...), and a `cwd`
under the system temp directory: a fresh work directory created for this call and deleted
after it. Try `/etc/passwd` or a file in your home directory: also blocked.

The tool never ran inside the server. The registry parsed `studio_peek.py` for its schema
and runs its source in the sandbox on every call.

### 4. Deploy a script tool

Open **Script Tool Creator** (`/studio/script`), name it `snoop`, type **bash**, and use:

```bash
echo "pwd=$PWD"
cat "$1" | head -2
echo "jwt=${SAJHA_JWT_SECRET:-unset}"
curl -s -m 3 https://example.com >/dev/null && echo net-open || echo net-blocked
```

Deploy, then call it with `{"args": ["/path/to/sajhamcpserver/config/application.yml"]}`.
`stdout` shows a temp `pwd`, `jwt=unset` and `net-blocked`; `stderr` shows
`Permission denied` for the `cat`. The result shape (`stdout`, `stderr`, `exit_code`,
`success`) is the same as before the sandbox.

### 5. Grant what a tool needs

Open the tool config Studio wrote (`peek.json` in `config/tools/`). It has `"sandbox": {"network": "none"}`. Widen it:

```json
"sandbox": {
  "network": "allowlist",
  "allow_hosts": ["api.github.com:443"],
  "timeout_seconds": 20,
  "memory_mb": 256
}
```

The registry reloads the config. The tool may now open HTTPS connections to
`api.github.com` and nothing else (the kernel enforces the port; the runner enforces the
host name for Python code). Numbers above the administrator's `sandbox.max` are capped.

For a secret, the administrator lists its name in `sandbox.secrets_allowlist` in
`config/application.yml`, and the tool asks for it with `"secrets": ["GITHUB_TOKEN"]`; the
value is read from the server's environment at call time. `SAJHA_*` variables are never
handed out.

### 6. Try a stronger backend

If step 1 listed `bwrap` as available, restart the server with
`SAJHA_SANDBOX_DEFAULT_BACKEND=bwrap` (or set `sandbox.default_backend: bwrap`): the
sandbox then has its own root with only system libraries and the interpreter, so the
server's files do not exist at all. With Docker and the image pulled
(`docker pull python:3.13-slim`), `docker` runs each call in a fresh container with no
network. A single tool can choose with `"backend": "docker"` in its `sandbox` block.

### 7. Clean up

Delete both tools from Studio (**Delete if Exists**), or
`POST /admin/studio/delete` with `{"tool_name": "peek"}` and `{"tool_name": "snoop"}`.

## What you learned

- Studio Python code and script tools run in a sandbox, not in the server, and callers see
  the same tool contract.
- `GET /api/sandbox/status` reports what is enforced on your host.
- A tool's `sandbox` block grants network hosts, limits and secrets; the administrator's
  defaults and caps bound it.

## What next

- [Sandbox](../architecture/Sandbox.md): the threat model and the backends
- [Security Model](../security/Security%20Model.md): the rest of the server
- Next tutorial: [The sajha CLI and Claude Desktop](TUTORIAL_15_sajha_cli_and_claude_desktop.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
