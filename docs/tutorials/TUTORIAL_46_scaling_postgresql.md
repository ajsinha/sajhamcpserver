# Tutorial 46: PostgreSQL, Several Workers and the Load Harness

SAJHA starts on a SQLite file and one worker. This tutorial moves it to PostgreSQL by configuration
alone, runs several workers that share their protocol state through the state store, reads the
database connection pool on the System monitor and in `/metrics`, and measures the result with the
load harness. Setting up PostgreSQL is owned by [Database Setup](../getting-started/Database%20Setup.md);
the state store, several workers, the pool's failure behaviour and the published numbers are owned by
[Scaling and State](../architecture/Scaling%20and%20State.md); every key is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md). It continues
[Tutorial 13](TUTORIAL_13_run_sajha_on_several_workers.md), which runs several workers on Redis.

**What was verified.** Every step below was run as written on a checkout, against PostgreSQL 17 in a
throw-away `postgres:17-alpine` container, with a scratch cache directory (`SAJHA_CACHE_DIR`) and scratch
directory for loaded results (`SAJHA_BI_SCRATCH_DIR`), and the default offline mock LLM provider. The
outputs shown are from that run, shortened where marked; worker ids, timings and throughput are your
machine's. Redis was not available, so the `redis` state backend is described but not run (step 7).

## What you'll learn

- How SAJHA refuses to start on an empty PostgreSQL database, and the two files that fix it
- How the `SAJHA_DB_*` variables switch the database with no change to `config/application.yml`
- How several workers share MCP sessions and other protocol state through `state.backend: database`
- Where the database connection pool shows up: the System monitor, `/api/admin/system-monitor` and
  the `sajha_db_pool_*` metrics
- How the load harness measures `/mcp` on both protocol eras, and how its high-concurrency check
  passes or fails

## Prerequisites

- A checkout with its virtual environment ([Quick Start](../getting-started/Quick%20Start.md)).
- A PostgreSQL server you may create a database on, and `psql`. The tutorial uses a container; any
  server works:

```bash
docker run -d --name sajha-pg -e POSTGRES_USER=sajha -e POSTGRES_PASSWORD=tutorial \
  -e POSTGRES_DB=sajha -p 127.0.0.1:3196:5432 postgres:17-alpine
```

- The development API key `sja_test_admin_dev_key_0001` from `config/apikeys.json` (role `admin`).
  The examples use a server on port 3195.

## 1. Point SAJHA at PostgreSQL and run the check

Configuration alone switches the database. Set the connection keys in the environment (or give one
`SAJHA_DB_URL`, which replaces them all):

```bash
export SAJHA_DB_TYPE=postgresql SAJHA_DB_HOST=127.0.0.1 SAJHA_DB_PORT=3196 \
       SAJHA_DB_NAME=sajha SAJHA_DB_USER=sajha SAJHA_DB_PASSWORD=tutorial
.venv/bin/python -m sajha.db check; echo "exit $?"
```

```text
database:  postgresql+psycopg2://sajha:***@127.0.0.1:3196/sajha
database schema is not ready (postgresql+psycopg2://sajha:***@127.0.0.1:3196/sajha):
  missing tables (28): a2a_tasks, ai_conversation_turns, ai_conversations, api_keys, ... (shortened)
  SAJHA does not create or alter tables on postgresql. Create the schema, then the default roles and admin user:
    psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 3196 -U sajha -d sajha -f db/scripts/postgresql/schema.sql
    psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 3196 -U sajha -d sajha -f db/scripts/postgresql/seed.sql
  Check with:  python -m sajha.db check.  Guide: docs/getting-started/Database Setup.md
  (db.schema_check: warn starts anyway, with features failing where tables are missing.)
exit 3
```

SAJHA never runs DDL on PostgreSQL. The server itself would refuse to start with the same message.
`SAJHA_DB_NAME` defaults to `sajha`, the name used here.

## 2. Create the schema and the seed

Run the two commands the check printed (each file is one transaction):

```bash
export PGPASSWORD=tutorial
psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 3196 -U sajha -d sajha -f db/scripts/postgresql/schema.sql | tail -2
psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 3196 -U sajha -d sajha -f db/scripts/postgresql/seed.sql | tail -2
.venv/bin/python -m sajha.db check; echo "exit $?"
```

```text
CREATE INDEX
COMMIT
INSERT 0 7
COMMIT
database:  postgresql+psycopg2://sajha:***@127.0.0.1:3196/sajha
Schema is complete: every table and column SAJHA uses is present (28 tables).
exit 0
```

The seed creates the default roles and the `admin` user (password `admin123`; change it).

## 3. Start two workers on a shared state store

With more than one worker, protocol state (MCP sessions, tasks, OAuth codes, rate-limit counters,
approvals and the rest) must live in a shared store. `state.backend: database` keeps it in SAJHA's own
database, here PostgreSQL:

```bash
P=/tmp/t46; mkdir -p $P
SAJHA_STATE_BACKEND=database SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195 --workers 2
```

`/health` answers from either worker; each names itself and the backend:

```bash
for i in 1 2 3 4; do curl -s http://127.0.0.1:3195/health | python3 -c "
import json,sys; d=json.load(sys.stdin); print(d['db_type'], json.dumps(d['state']))"; done
```

```text
postgresql {"backend": "database", "shared": true, "prefix": "sajha:", "dialect": "postgresql", "poll_interval_ms": 500, "reachable": true, "tasks": "durable (database)", "worker_id": "oryxpro:1004903:44acd1", "workers_hint": 2}
postgresql {"backend": "database", "shared": true, "prefix": "sajha:", "dialect": "postgresql", "poll_interval_ms": 500, "reachable": true, "tasks": "durable (database)", "worker_id": "oryxpro:1004902:67018b", "workers_hint": 2}
...
```

A load balancer can check `state.reachable`. With `memory` and several workers, start-up logs a
warning instead, because sessions would not be shared.

## 4. One MCP session, served by both workers

Open a 2025-11-25 session and make four calls on it. Requests land on either worker; the session lives
in the store, so every call succeeds:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'; U=http://127.0.0.1:3195/mcp
A='Accept: application/json, text/event-stream'; C='Content-Type: application/json'
SID=$(curl -s -D - -o /dev/null $U -H "$K" -H "$C" -H "$A" -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
  "params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"t46","version":"1"}}}' \
  | grep -i mcp-session-id | tr -d '\r' | awk '{print $2}')
curl -s $U -H "$K" -H "$C" -H "$A" -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' -o /dev/null -w "%{http_code}\n"
for i in 1 2 3 4; do
  curl -s $U -H "$K" -H "$C" -H "$A" -H "Mcp-Session-Id: $SID" -H 'MCP-Protocol-Version: 2025-11-25' \
    -d '{"jsonrpc":"2.0","id":'$i',"method":"tools/call","params":{"name":"calc_compound_interest","arguments":{"principal":1000,"rate":5,"years":'$i'}}}' \
  | python3 -c "import sys,json; d=json.loads(sys.stdin.read().split('data: ')[-1]); print(d['id'], d['result']['structuredContent']['future_value'])"
done
```

```text
202
1 1051.16
2 1104.94
3 1161.47
4 1220.9
```

The store's rows are in the `sajha_state` table:

```bash
psql -h 127.0.0.1 -p 3196 -U sajha -d sajha \
  -c "select split_part(k, ':', 2) as kind, count(*) from sajha_state group by 1 order by 2 desc"
```

```text
  kind   | count
---------+-------
 obs     |     2
 notice  |     2
 worker  |     2
 notices |     1
 auth    |     1
 mcp     |     1
(6 rows)
```

`worker` holds each worker's heartbeat, `mcp` the session, `obs` each worker's metrics snapshot.

## 5. The connection pool on the System monitor

Each worker keeps one pool of database connections (`db.pool.size`, default 10, plus
`db.pool.max_overflow`, by default as many again). A request that finds no free connection within
`db.pool.timeout_seconds` (default 5) is answered at once with HTTP 503 and `Retry-After: 1` instead of
hanging. The **System monitor** page (Admin, Operations; `/admin/system-monitor`) has a "Database Connection
Pool" panel per worker; the JSON behind it is `db_pool` in `/api/admin/system-monitor`:

```bash
curl -s http://127.0.0.1:3195/api/admin/system-monitor -H "$K" | python3 -c "
import json,sys; print(json.dumps(json.load(sys.stdin)['db_pool'], indent=1))"
```

```text
{
 "workers": [
  {
   "worker": "oryxpro:1004903:44acd1",
   "this_worker": true,
   "db_type": "postgresql",
   "url": "postgresql+psycopg2://sajha:***@127.0.0.1:3196/sajha",
   "pool_class": "CountingQueuePool",
   "exhausted_total": 0,
   "waiting": 0,
   "size": 10,
   "max_overflow": 10,
   "timeout_seconds": 5.0,
   "checked_out": 0,
   "idle": 1,
   "overflow_in_use": 0,
   "capacity": 20
  },
  {
   "worker": "oryxpro:1004902:67018b",
   "this_worker": false,
   "as_of": 1791782249.9714339,
   "size": 10.0,
   ...
  }
 ]
}
```

The worker that answered reports its live pool; the others report their last published snapshot
(`as_of`). The password in the URL is always hidden.

The same figures are Prometheus metrics. `/metrics` is for administrators by default
(`observability.metrics.auth: admin`: a console session or an administrator's JWT, not an API key), so
sign in first:

```bash
T=$(curl -s -X POST http://127.0.0.1:3195/api/auth/login -H "$C" \
  -d '{"user_id":"admin","password":"admin123"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s http://127.0.0.1:3195/metrics -H "Authorization: Bearer $T" | grep -E "^sajha_db_pool_(size|checked_out|exhausted_total)"
```

```text
sajha_db_pool_size{db_type="postgresql",worker="oryxpro:1004903:44acd1"} 10
sajha_db_pool_size{db_type="postgresql",worker="oryxpro:1004902:67018b"} 10
sajha_db_pool_checked_out{db_type="postgresql",worker="oryxpro:1004903:44acd1"} 0
sajha_db_pool_checked_out{db_type="postgresql",worker="oryxpro:1004902:67018b"} 0
sajha_db_pool_exhausted_total{db_type="postgresql",worker="oryxpro:1004903:44acd1"} 0
sajha_db_pool_exhausted_total{db_type="postgresql",worker="oryxpro:1004902:67018b"} 0
```

`deployment/observability/sajha-alerts.yml` has the `SajhaDbPoolExhausted` rule on the last one. Stop
the server before the next step (it needs the port).

## 6. Measure with the load harness

`tools/bench/bench.py` starts its own server for each configuration (backend and worker count) on a
scratch database with a scratch API key, and drives `/mcp` on both eras with `tools/list` and
`tools/call` on a local calculator, new arguments every call so the cache never answers. A short run of
the standard scenario on the database store with two workers:

```bash
.venv/bin/python tools/bench/bench.py --configs database:2 --port 3195 \
  --duration 5 --warmup 1 --concurrency 16 --out $P/bench --scratch $P
```

```text
[bench] database:2: starting on port 3195 (scratch /tmp/t46/sajha-bench-database2-3mayh5uc)
[bench]   modern tools/list x16      100.8 req/s  p50 153.69 ms  p99 274.96 ms  slowest 297.23 ms  errors 0  shed 0  hung 0
[bench]   modern tools/call x16      476.8 req/s  p50 31.44 ms  p99 71.09 ms  slowest 90.98 ms  errors 0  shed 0  hung 0
[bench]   legacy tools/list x16       56.6 req/s  p50 220.72 ms  p99 629.95 ms  slowest 701.27 ms  errors 0  shed 0  hung 0
[bench]   legacy tools/call x16      535.0 req/s  p50 29.26 ms  p99 77.98 ms  slowest 158.45 ms  errors 0  shed 0  hung 0
[bench] wrote /tmp/t46/bench/bench-20261012T051828Z.json and /tmp/t46/bench/bench-20261012T051828Z.md
```

The `.md` file is a table with the hardware, the load and the SAJHA version and commit; the `.json` has
every number.

The high-concurrency scenario adds `/health` probes during every phase and a pass/fail verdict (exit 2
on a fail): no request unanswered or slower than `--max-latency`, `/health` within `--health-bound`,
errors (503 shedding excluded) under `--max-error-rate`. With `SAJHA_BENCH_PG_URL` it also runs on
PostgreSQL, in a scratch database it creates from the schema files and drops afterwards (the URL is
never printed). Here with a deliberately small pool of four connections per worker:

```bash
SAJHA_BENCH_PG_URL=postgresql://sajha:tutorial@127.0.0.1:3196/sajha \
  .venv/bin/python tools/bench/bench.py --scenario highconc --configs pg:2 --levels 64,256 \
  --duration 5 --warmup 1 --pool-size 4 --pool-timeout 1 --port 3195 --out $P/bench-hc --scratch $P
tail -8 $P/bench-hc/*.md
```

```text
Check: no request unanswered or slower than 30.0 s, /health answering within 5.0 s throughout, errors (503 shedding excluded) at most 1.0%. Verdict: **pass**.

| Database | Workers | Era | In flight | Requests | Shed (503) | Errors | Hung | Throughput (req/s) | p50 (ms) | p99 (ms) | Slowest (ms) | /health max (ms) | Load avg | Check |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| PostgreSQL | 2 | modern (2026-07-28) | 64 | 2638 | 0 | 0 | 0 | 527.6 | 110.53 | 374.61 | 460.63 | 43.57 | 7.16 | pass |
| PostgreSQL | 2 | legacy (2025-11-25) | 64 | 2411 | 0 | 0 | 0 | 482.2 | 124.21 | 258.42 | 349.48 | 70.31 | 7.23 | pass |
| PostgreSQL | 2 | modern (2026-07-28) | 256 | 2209 | 0 | 0 | 0 | 441.8 | 496.96 | 741.34 | 904.39 | 145.73 | 7.05 | pass |
| PostgreSQL | 2 | legacy (2025-11-25) | 256 | 2278 | 0 | 0 | 0 | 455.6 | 558.72 | 672.85 | 696.95 | 903.79 | 6.97 | pass |
```

Afterwards no `sajha_bench_*` database is left on the server. The load generator shares the machine
with the server, so compare rows with each other rather than reading them as capacity; the published
run, with its machine and date, is in [Scaling and State §9](../architecture/Scaling%20and%20State.md#9-measured-performance).

## 7. Redis, and going back to SQLite

- **Redis.** `SAJHA_STATE_BACKEND=redis` with `SAJHA_STATE_REDIS_URL=redis://host:6379/0` puts the state
  store in Redis instead; the database stays wherever `db.*` says. A store that does not answer stops
  start-up. The harness runs its `redis:N` configurations only when a server answers at
  `--redis-url`, and otherwise skips them with a note. [Tutorial 13](TUTORIAL_13_run_sajha_on_several_workers.md)
  runs several workers on Redis.
- **Back to SQLite.** Unset the `SAJHA_DB_*` variables (or set `SAJHA_DB_TYPE=sqlite`); SQLite creates its
  own tables from `db/scripts/sqlite/schema.sql`. Nothing is copied between the two databases.
- **Several hosts.** Workers on one host share the data directory and therefore their secrets; separate
  hosts must share the JWT and session secrets and the OAuth signing key
  ([Scaling and State §5](../architecture/Scaling%20and%20State.md#5-secrets-every-worker-must-share)).

## Summary

- `SAJHA_DB_*` (or `SAJHA_DB_URL`) switches the database; `python -m sajha.db check` and the start-up check
  refuse an incomplete PostgreSQL schema and print the `psql` commands that complete it
- `state.backend: database` or `redis` lets several workers share sessions and the other protocol state;
  `/health` shows the backend and the worker
- The connection pool is sized by `db.pool.*`, sheds with 503 instead of hanging, and is visible per worker
  on the System monitor and in `sajha_db_pool_*`
- `tools/bench/bench.py` measures `/mcp` on both eras; `--scenario highconc` adds a pass/fail check and runs
  on PostgreSQL with `SAJHA_BENCH_PG_URL`

## Next

- Failure behaviour and sizing: [Scaling and State](../architecture/Scaling%20and%20State.md)
- On Kubernetes: [Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md)
- [Tutorial 47: Federation at Gateway Scale](TUTORIAL_47_federation_gateway.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
