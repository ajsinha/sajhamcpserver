# Scaling and State

How SAJHA runs as several worker processes on one host, or on several hosts behind a load
balancer: which state a worker keeps, which state must be shared, where shared state is
stored, and what still stays per process.

This document owns the topic. The configuration keys and their defaults are in the
[Configuration Reference](../getting-started/Configuration%20Reference.md#state). The
walkthrough is [Tutorial 13](../tutorials/TUTORIAL_13_run_sajha_on_several_workers.md). The
terms (state store, durable task) are defined in the [Glossary](../../GLOSSARY.md).

The default is `state.backend: memory`. With that default, one worker behaves exactly as it
did before the state store existed. Nothing below changes a single-process deployment.

---

## 1. The problem

A request can reach any worker. Before this change, each of the following lived in one
process's memory, so it broke as soon as two workers served the same clients:

- An OAuth authorization code issued by worker A was unknown to worker B. The token request
  failed with `invalid_grant`.
- A 2025-11-25 `Mcp-Session-Id` minted on A was answered with 404 by B.
- A 2026-07-28 task created on A answered `Unknown taskId` on B, and was lost when A
  restarted.
- Rate limits and the sign-in throttle counted per worker. N workers allowed N times the
  limit, and N times the daily LLM token budget.
- A tool enabled on A produced `notifications/tools/list_changed` only on A's
  `subscriptions/listen` streams.

## 2. The state store

`sajha/core/state/` defines one interface, `StateStore` (in `base.py`), with three
implementations. Each process builds one store from `state.*` at start-up
(`sajha/core/state/__init__.py`).

| Operation | memory (`memory.py`) | redis (`redis_store.py`) | database (`database.py`) |
|---|---|---|---|
| get / set / add / pop / delete, with TTL | dict of JSON strings, expiry checked on access | strings with `PX` | `sajha_state` rows with `expires_at` |
| `update(key, fn)`: atomic read-modify-write | under a lock | `WATCH`/`MULTI`, retried | optimistic `ver` column, retried |
| `incr`: atomic counter | under a lock | `INCRBYFLOAT` plus a TTL set in Lua | `update` |
| sliding windows (rate limits) | list of timestamps | one sorted set per key, trimmed in Lua | JSON list of timestamps |
| leases: `lease_claim` / `lease_renew` / `lease_release` / `lease_holder` (§4.7) | `add` and `update` | `SET NX PX` and `WATCH`/`MULTI` | `add` and `update` |
| publish / subscribe | direct call in-process | Redis pub/sub on `<prefix>chan:*`, one listener thread per process, reconnects | `sajha_state_events` table polled every `state.database.poll_interval_ms` |
| shared between processes | no | yes | yes (same database) |

Values are JSON on every backend, including memory, so code that works on the memory backend
also works on the shared ones. Every key and channel carries `state.key_prefix`, so several
deployments can share one Redis or one database.

Choosing a backend:

- **memory**: one worker. This is the default.
- **redis**: several workers or hosts. Pub/sub latency is effectively zero. It needs a Redis
  server and the optional `redis` package.
- **database**: several workers on one host with SQLite, or several hosts with PostgreSQL
  (`db.*`, or `state.database.url`). No extra service is needed. Change notifications arrive
  one poll interval late.

### Durable tasks

MCP task records go to a second store (`get_task_record_store()`). When
`state.tasks.durable` is on, that store is the database. Its default, `auto`, turns it on for
the redis and database backends. A durable task's record (status, result, error, pending
input, answers and the call spec) survives a restart and is visible to every worker. See §4.4.

### Worker identity and liveness

Each process has a `WORKER_ID` (`host:pid:random`). With a shared backend it writes a
heartbeat key `worker:<id>` (TTL 30 s, refreshed every 10 s), and deletes it on a graceful
shutdown. A task or async job whose record names a worker without a heartbeat is
**orphaned**. With the memory backend there is only one process, so any other worker ID is
dead.

## 3. Inventory of process state

Every piece of per-process state found in the code, with its classification:

- **Shared**: the state now lives in the state store.
- **Durable**: the state now lives in the database.
- **Already shared**: the state was in the database or in files before this change.
- **Local**: the state stays per process on purpose. The reason is in the last column.
- **Local, relayed** or **Local, published**: the state stays per process, and the messages
  (relayed) or snapshots (published) other workers need go through the store.
- **Stateless**: nothing is kept; the client carries it, signed.

| State | Code | Class | Where it lives now / why it stays local |
|---|---|---|---|
| OAuth pending consent requests | `sajha/auth/oauth/authorization_server.py` | Shared | `oauth:pending:<id>`, TTL 600 s. The cap of 5000 pending requests is enforced only where counting is cheap (memory, database). Redis relies on the TTL and the IP rate limit. |
| OAuth authorization codes | same | Shared | `oauth:code:<sha256>`. Redemption is one atomic `update`, which also fixes the refresh-token family, so a replay on any worker revokes exactly that family. |
| OAuth refresh tokens and revoked families | same | Shared | `oauth:refresh:<sha256>`, rotated with an atomic `update`. `oauth:revoked:<family>` is checked on every use. |
| Dynamically registered OAuth clients (DCR) | `sajha/auth/oauth/clients.py` | Shared | `oauth:dcr:<client_id>`, kept until deleted (no expiry), plus a counter for the 1000-client cap. A local copy is cached after the first lookup. |
| Client ID Metadata Document cache | same | Local | A cache of public documents. A miss costs one fetch. |
| OAuth signing key | `sajha/auth/oauth/keys.py` | Already shared (file) | The key file is in the data directory. Hosts that do not share that directory set `mcp.auth.builtin.signing_key_pem`. |
| MCP 2025-11-25 sessions | `sajha/core/mcp_sessions.py` | Shared | `mcp:session:<id>`, with an idle TTL of 24 h that slides at most once a minute. The record in the store is the authority: a session deleted on one worker is gone on all of them. |
| Server-to-client requests waiting on an open SSE stream | same (`pending` futures) | Local, relayed | A future cannot leave its event loop. A client's answer that reaches another worker is published on `mcp.sessions`, and the worker holding the stream resolves it. |
| Legacy 2024-11-05 HTTP+SSE queues | `sajha/core/mcp_sse_relay.py` (used by `sajha/routes/mcp_routes.py`) | Local, relayed | The queue stays with the open stream. `mcp:sse:<id>` records which streams exist, and a POST to another worker is published on `mcp.sse`. |
| MRTR `requestState` | `sajha/core/mcp_mrtr.py` | Stateless | Signed and carried by the client. Every worker needs the same secret (§5). |
| MCP 2026-07-28 tasks | `sajha/core/mcp_tasks.py` | Durable, or Shared | Records are in the task record store (§4.4). The running coroutine stays on its worker. |
| Legacy `TaskManager`, `ElicitationManager`, `SamplingManager` | `sajha/core/mcp_2025_11_25.py` | Local (inert) | Nothing in the server creates entries in them, so they are always empty. |
| `subscriptions/listen` streams and change-bus subscriptions | `sajha/core/change_bus.py`, `sajha/core/mcp_modern.py` | Local, relayed | A stream belongs to one connection. Events are relayed on the `changes` channel (§4.5). |
| Rate limits (`auth`, `api`, `user`, `key`) | `sajha/security.py` (`RateLimiter`) | Shared | Sliding windows `ratelimit:<name>:<key>`. |
| Sign-in IP throttle | `sajha/security.py` (`FailureThrottle`) | Shared | Window `loginfail:<key>`. |
| Account lockout | `sajha/auth/__init__.py` (`AuthManager.sign_in`) | Already shared (database) | The `failed_attempts` and `locked_until` columns on the user row. |
| Web sign-in sessions | `sajha/auth/__init__.py`, `sajha/auth/jwt_handler.py` | Stateless (JWT) | The `sajha_token` cookie holds a signed JWT and the user is reloaded from the database on each request. Every worker needs the same JWT secret (§5). |
| LLM token usage and daily budgets | `sajha/ai/gateway.py` (`TokenTracker`) | Shared | `llm:usage:<user>` and the daily counters `llm:daily:user:*` and `llm:daily:role:*`, which expire after 2 days. With the memory backend each gateway keeps private counters, as before. |
| LLM response cache, provider health, provider circuit breakers | `sajha/ai/gateway.py` | Local | Caches and health probes. Each worker learning them on its own costs some duplicate calls, not correctness. |
| Async executor queue | `sajha/core/async_executor.py` | Local | The work runs where it was submitted. |
| Async executor task records | same | Shared | Written through to `async:task:<id>` with a shared backend, so any worker can read, list, cancel (while queued) and retry a job. Delivery headers stay in the submitting process, so a retry on another worker sends no custom headers. A queued or running job of a dead worker is reported failed. |
| Tool output cache | `sajha/core/cache.py` | Already shared (files) | Files under `data/cache/`, shared by the workers of one host. Each host keeps its own. A miss only costs a call. A per-user tool keys its entries by caller (§4.8). |
| Tool circuit breakers | `sajha/core/circuit_breaker.py` | Local | Each worker opens its breaker after its own failures. A shared breaker would let one worker's network fault block every worker. |
| Metrics | `sajha/observability/metrics.py` | Local, published | Each worker keeps its own families. With a shared backend each worker also publishes a snapshot (`obs:metrics:<worker id>`), and `/metrics` merges every live worker's snapshot with a `worker` label ([Observability](Observability.md#24-several-workers)). The JSON `/api/metrics*` views show the worker that answered. |
| Usage ledger | `sajha/observability/usage.py` | Already shared (database) | One table in SAJHA's database, so the Usage & cost page sees every worker. |
| Alert-rule windows | `sajha/observability/alerts.py` | Local | Each worker evaluates its own traffic; with several workers, alert in Prometheus instead. |
| Execution replay | `sajha/core/tool_health.py` | Local | Per-worker history. The replay views show the worker that answered. |
| WebSocket sessions | `sajha/routes/ws_routes.py` | Local | A WebSocket is one connection to one worker. The admin listing shows that worker's connections only. |
| Tool, prompt, user and API-key configuration | `sajha/tools/tools_registry.py`, `sajha/core/prompts_registry.py`, the `users` / `api_keys` tables | Already shared (files and database) | Each worker loads and hot-reloads the files. The local tool-config poller runs every 5 s, so a tool enabled on one worker reaches the others' registries within about that time. |
| Federation upstream connections and breakers | `sajha/federation/` | Local | Each worker opens its own connections to upstreams. The upstream list and approvals are in the federation store (storage backend), and an upstream's `max_calls_per_minute` window is in the state store. |
| Log de-duplication sets, provider instances, glossary cache | `sajha/core/mcp_modern.py`, `sajha/core/mcp_apps.py`, `sajha/ai/providers/__init__.py`, `sajha/web/glossary.py` | Local | Process-local helpers that hold no client-visible state. |

## 4. Component designs

### 4.1 OAuth

`AuthorizationStore` holds no data of its own. Every operation is a state-store call, and
the two that must be single-use (redeeming a code, rotating a refresh token) are one atomic
`update` each. The consent form may be answered on another worker, because the pending
request is in the store and the CSRF token is derived from the session secret.

### 4.2 Sessions and server-to-client requests

`MCPSessionStore` keeps a local object per session, which holds the pending futures. With a
shared store attached at start-up, it also writes a record. `get` reads the record on every
request: a missing record means the session ended or expired, and the local object is
dropped. Request IDs for server-to-client requests carry the worker suffix, so they stay
unique across workers.

### 4.3 Legacy HTTP+SSE

The GET stream registers its ID in the store and refreshes the TTL while it is open. A POST
for that ID on another worker is published on the channel and put on the stream's queue by
its worker.

### 4.4 Tasks

- `create` writes the record with `worker = WORKER_ID` and a JSON **call spec**: the tool
  name, its arguments, the client capabilities and the caller's session. The worker then
  runs the coroutine and writes each outcome with an atomic `update` that never overwrites
  a terminal status, so a cancel always wins over a late completion.
- `tasks/get` reads the record on any worker, scoped to its owner.
- `tasks/cancel` marks the record `cancelled` on whichever worker receives it. If the job
  runs elsewhere, the cancel is published on `mcp.tasks` and the running worker cancels it.
- `tasks/update` (answers to `input_required`) claims the task atomically. If the runner
  is not on this worker (another worker started it, or the server restarted), the runner is
  rebuilt from the call spec. The 2026-07-28 server registers that resumer in its
  constructor, and the next round runs on this worker. A task waiting for input therefore
  survives a restart when tasks are durable.
- **Orphans.** A `working` task whose worker has no heartbeat is marked `failed` with
  `-32603` "The worker running this task stopped before it finished" when it is read. It is
  never re-run on another worker, because SAJHA cannot assume that tools are idempotent.

### 4.5 Change bus

`ChangeBus.attach_store` (called at start-up for shared backends) publishes every event on
the `changes` channel as well, tagged with the bus's own origin. Events from other workers
go to this worker's `Subscription`s only: listen streams, legacy SSE and WebSocket pushes.
They do not go to synchronous listeners, which stay local. Coalescing still applies per
subscriber.

Bursts are kept off the store. The tools registry announces bulk work (start-up loading,
reloads, the config poller's scan, composite and federation sync) once at the end, and not
at all when the catalog it would list is unchanged; re-registering an identical tool or
unregistering an unknown one announces nothing. On the relay itself, the first of a run of
identical events goes out at once and any repeats within `ChangeBus.RELAY_WINDOW_SECONDS`
(0.5 s) become one trailing event.

### 4.6 Counters

Rate limits, the sign-in throttle and LLM budgets are sliding windows or counters in the
store. They are atomic on every backend, so two workers cannot both let the last allowed
request through.

### 4.7 Leases

Some work must run on exactly one worker at a time for as long as it runs: a gossip agent,
a purge job, a long scheduler loop. A one-slot claim (`add` of the worker id with a TTL,
never renewed, as workflow cron and quality probes use to fire each slot once) cannot
express that. A **lease** can: its holder renews it while it works, and a holder that
stops (crash, hang) loses it after one TTL, so another worker takes over.

| Call | Semantics |
|---|---|
| `store.lease_claim(key, holder, ttl)` | atomic add of `{"holder", "claimed", "renewed", "ttl"}` with the TTL; True when `holder` now holds it (a holder that already holds it renews) |
| `store.lease_renew(key, holder, ttl=None)` | conditional update: extends the TTL (default the lease's own) only while `holder` holds it; False when it expired or someone else holds it |
| `store.lease_release(key, holder)` | deletes it only when `holder` holds it |
| `store.lease_holder(key)` | the holder now, or None; also reads one-slot claims (their value is the worker id) |

They are built on `add` and `update`, which each backend already makes atomic, so they mean
the same on memory, redis and database. `sajha/core/state/lease.py::Lease` keeps one held:
`try_acquire()` claims and starts a renewer thread (every `ttl / 3` by default), `release()`
gives it up, and when a renewal finds the lease gone, `held` turns False and `on_lost` is
called: the holder must stop the guarded work, because another worker may already be doing
it. A renewal that fails because the store is unreachable is retried until the TTL runs out.
Pick a TTL several renewal intervals long; the guarantee is "at most one holder whose lease
has not expired", so work that cannot tolerate an overlap after a long pause (a GC stop
beyond the TTL) must also check `held` before each step. The one-slot claims of cron and
probes are unchanged.

### 4.8 Per-user cache keys

The tool output cache keys a result by tool name and arguments, so by default every caller
shares it. A tool whose result depends on who asks sets `"cache_per_user": true` in its
config: `sajha/core/cache.py::cache_scope` then adds `user:<user id>` (from
`sajha.observability.caller`) to the key, so one user's cached result is never served to
another; all anonymous callers share one key. Federated tools default to per-user keys
(`cache.per_user_federated: true`; an upstream's `cache_per_user` overrides it), because
the upstream may answer differently per caller. Tools bound to a connected account are
never cached at all. Invalidating a tool removes every user's entries.

## 5. Secrets every worker must share

The state store moves data. These secrets must also be identical everywhere:

| Secret | Used for | How to share it |
|---|---|---|
| JWT secret | web sign-in, API JWTs | env `JWT_SECRET` (or a shared `auth.secrets_file`) |
| Session secret | OAuth consent CSRF, and the default MRTR key | env `SESSION_SECRET` (or a shared `auth.secrets_file`) |
| MRTR state secret | `requestState` signatures | `mcp.mrtr.state_secret`, or the session secret |
| OAuth signing key | access tokens | a shared data directory, or `mcp.auth.builtin.signing_key_pem` |

Workers on one host share the data directory, so they already agree on these. When a
secret is not configured, it is generated once into `auth.secrets_file`. Separate hosts must
set them through the environment.

## 6. Running several workers

- `python run_server.py --workers N` starts N uvicorn worker processes. In that mode the
  app is built from `sajha.app:create_app` in each worker, and `WEB_CONCURRENCY` is set so
  each worker knows the count. The container image honours `UVICORN_WORKERS`.
- At start-up, each worker builds the store. A shared store that does not answer stops
  start-up, so the deployment fails instead of silently splitting state. Each worker then
  attaches the change bus, sessions, the SSE relay and the task-cancel relay, and logs one
  line naming the backend.
- When the environment says there are several workers (`SAJHA_WORKERS`,
  `WEB_CONCURRENCY`, `UVICORN_WORKERS`, `GUNICORN_WORKERS`, or `--workers`/`-w` on the
  command line) and the backend is `memory`, start-up logs a warning that says what will
  break.
- `GET /health` has a `state` object with `backend`, `reachable`, `tasks` (`memory`,
  `redis`, or `durable (database)`), `worker_id` and `workers_hint`. A load balancer can
  check `state.reachable`.

Deployment recipes: [deployment/README.md](../../deployment/README.md#several-workers-or-hosts);
on Kubernetes, several replicas with a shared backend are covered by
[Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#4-several-replicas).
The Hetzner and local AWS compose files have an optional `scale` profile that starts Redis.
The AWS CDK stack runs several Fargate tasks with `SAJHA_STATE_BACKEND=database` on RDS.

## 7. Failure behaviour and limits

- **Redis unavailable at runtime.** Requests that touch shared state fail with HTTP 500
  until Redis is back. The pub/sub listener reconnects with backoff. Nothing falls back to
  per-process state, because that fallback would silently break the guarantees in §1.
- **Database backend latency.** Pub/sub is a polled table, so change notifications and
  task cancels arrive one poll interval late (500 ms by default). Event rows are deleted
  after a minute.
- **Blocking calls.** State-store calls are synchronous, and some are made on the event
  loop. With Redis or a local database they take well under a millisecond to a few
  milliseconds. A remote PostgreSQL adds its round-trip time.
- **A stream belongs to one worker.** An open SSE or WebSocket stream lives where it was
  opened. Only the messages that must reach it are relayed. If that worker dies, the stream
  ends and the client reconnects, as it would after a restart.
- **SQLite on several hosts** is not supported. Use PostgreSQL or Redis.

## 8. Tests

- `tests/test_state_store.py` runs the store contract, and every migrated component with
  two instances standing for two workers, against memory, fakeredis (when `fakeredis` and
  `lupa` are installed), a real Redis (`SAJHA_TEST_REDIS_URL`, skipped when none answers)
  and SQLite.
- `tests/test_state_multiworker.py` starts two real server processes that share one
  database and backend (database, and redis when available). It checks over HTTP that a
  code issued by A is redeemed by B, a task created on A is read and cancelled on B, sign-in
  failures add up across workers, and an event on A reaches a `subscriptions/listen` stream
  on B. It also starts `run_server.py --workers 2` and checks that both workers report the
  shared backend.
- `tests/test_state_lease.py` runs the lease contract (exclusive and re-entrant claim,
  renewal only by the holder, expiry and takeover, release, one-slot claims, a race of
  six claimants, the `Lease` keeper's renewal and loss) on the same backends; the real
  Redis case is skipped when no server answers at `SAJHA_TEST_REDIS_URL`.
