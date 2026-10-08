# Tutorial 13: Run SAJHA on Several Workers

In this tutorial you run SAJHA as more than one process and let the processes share their
state through Redis. You will see what SAJHA warns about when the state is not shared,
start several workers on a shared store, check them with `/health`, and watch a change
made on one server reach a client connected to another. The design, and the list of what
is shared and what stays per process, is in
[Scaling and State](../architecture/Scaling%20and%20State.md).

## What you'll learn

- Why several workers need a shared state store
- How to switch `state.backend` to Redis (or to the database)
- How to read the `state` block of `/health`
- How a change notification travels from one worker to another

## Prerequisites

- A SAJHA checkout with its virtual environment ([Tutorial 1](TUTORIAL_01_getting_started.md))
- Docker, to run Redis (or any Redis server you already have)
- `curl`

## Steps

### 1. See the warning

Start four workers with the default memory backend:

```bash
python run_sajha_web.py --workers 4
```

Each worker prints a warning like this one:

```
Running 4 workers with state.backend=memory: OAuth codes, MCP sessions, tasks, rate limits
and change notifications are per worker and WILL break across workers. ...
```

The warning is accurate. A client that gets an OAuth code from one worker and exchanges it
at another gets `invalid_grant`, and a 2025-11-25 session ID is unknown to three of the four
workers. Stop the server (Ctrl+C).

### 2. Start Redis and install the client library

```bash
docker run -d --name sajha-redis -p 127.0.0.1:6379:6379 redis:7-alpine
pip install "redis>=5"
```

### 3. Point SAJHA at Redis

Set the backend through the environment (or set `state.backend: redis` in
`config/application.yml`):

```bash
export SAJHA_STATE_BACKEND=redis
export SAJHA_STATE_REDIS_URL=redis://127.0.0.1:6379/0
python run_sajha_web.py --workers 4
```

The warning is gone. If Redis is not reachable, start-up stops with an error instead of
running with split state.

### 4. Check `/health`

```bash
for i in 1 2 3 4 5 6; do curl -s http://127.0.0.1:3002/health | python -c \
  'import json,sys; s=json.load(sys.stdin)["state"]; print(s["backend"], s["reachable"], s["worker_id"])'; done
```

Each new connection may reach a different worker, so the `worker_id` changes while the
backend stays `redis`. The `tasks` field reads `durable (database)`, because
`state.tasks.durable: auto` keeps MCP task records in SAJHA's database whenever the backend is
shared.

### 5. Watch a change cross from one server to another

Two servers on two ports make the hand-off visible. Stop the server, then start two
single-worker servers on the same Redis and the same database:

```bash
python run_sajha_web.py --port 3002 &
python run_sajha_web.py --port 3003 &
```

In a second terminal, open a 2026-07-28 `subscriptions/listen` stream on port **3003**:

```bash
curl -sN http://127.0.0.1:3003/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: subscriptions/listen' \
  -d '{"jsonrpc":"2.0","id":1,"method":"subscriptions/listen","params":{
        "notifications":{"toolsListChanged":true},
        "_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28",
                 "io.modelcontextprotocol/clientCapabilities":{},
                 "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"}}}}'
```

The stream starts with `notifications/subscriptions/acknowledged`. Now disable and re-enable
a tool on port **3002**, signed in as admin:

```bash
TOKEN=$(curl -s http://127.0.0.1:3002/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","password":"admin123"}' | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3002/api/admin/tools/av_atr/disable
curl -s -X POST -H "Authorization: Bearer $TOKEN" http://127.0.0.1:3002/api/admin/tools/av_atr/enable
```

The stream on port 3003 receives `notifications/tools/list_changed`. The server on 3002
published the event on the store's `changes` channel, and 3003 passed it to its listeners.
(Port 3003's own registry picks up the edited tool file within about 5 seconds, through its
file monitor.)

### 6. Without Redis: the database backend

Workers on one host can share state through SAJHA's own database instead, with no extra
service:

```bash
export SAJHA_STATE_BACKEND=database
python run_sajha_web.py --workers 4
```

The `database` backend stores state in two tables, `sajha_state` and `sajha_state_events`,
which it creates on first use. Pub/sub is a polled table, so the notification in step 5
arrives up to `state.database.poll_interval_ms` (500 ms by default) later. For several
hosts, use PostgreSQL (`db.type: postgresql`) or Redis. SQLite cannot be shared across hosts.

## What you built

- Several SAJHA workers that agree on OAuth codes, sessions, tasks, rate limits and LLM
  budgets
- A change notification that reaches clients whichever worker they are connected to

## What next

- For production compose files, use the optional `scale` profile in
  [deployment/hetzner/docker-compose.yml](../../deployment/hetzner/docker-compose.yml), and
  read [deployment/README.md](../../deployment/README.md#several-workers-or-hosts)
- Before you add a second host, check the secrets that every worker must share in
  [Scaling and State §5](../architecture/Scaling%20and%20State.md#5-secrets-every-worker-must-share)
- Next tutorial: [Sandboxed Studio Tools](TUTORIAL_14_sandboxed_studio_tools.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
