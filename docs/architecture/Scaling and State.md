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
| Personal document index (connected-account sources) | `sajha/ai/rag/personal.py` | Local, shared claim | The passages are in a sqlite_vec file on the host (or process memory), so each host syncs for itself. Workers sharing one file take the lease `rag:accounts:sync:<host>:<file>:<owner>:<source>` (§4.7) so one syncs a user's source at a time; when and what each last synced is kept per process. |
| Workflow trigger claims | `sajha/workflows/service.py` | Shared claim | One-slot claims fire each cron slot (`wf:cron:...`), each change-bus event per trigger (`wf:evclaim:...`) and each file poll (`wf:filepoll:...`) on one worker; the run records themselves are in the database ([Workflows](Workflows.md#4-triggers)). |
| Rate limits (`auth`, `api`) | `sajha/security.py` (`RateLimiter`) | Shared | Sliding windows `ratelimit:<name>:<key>`. |
| Policy rate limits and quotas | `sajha/policy/engine.py` | Shared | Sliding windows `policy:rate:<rule>:<scope>` and period counters `policy:quota:<rule>:<scope>:<period>` ([Policy and Audit](Policy%20and%20Audit.md)). |
| Signed-out tokens | `sajha/auth/revocation.py` | Shared | `auth:revoked:<jti>` until the token would have expired. With `memory`, only the worker that handled the sign-out refuses the token. |
| Single sign-on state | `sajha/auth/sso.py` | Shared | `sso:state:<state>` (state, nonce and PKCE verifier, ten minutes, taken once) and `sso:idt:<jti>` (the ID token kept for the provider sign-out). |
| The API keys dump (`config/apikeys_db.json`) | `sajha/auth/credential_jobs.py` | Shared claim | One worker writes each interval: a one-slot claim `auth:apikeys_dump:<slot>` (§4.7). |
| Sign-in IP throttle | `sajha/security.py` (`FailureThrottle`) | Shared | Window `loginfail:<key>`. |
| Account lockout | `sajha/auth/__init__.py` (`AuthManager.sign_in`) | Already shared (database) | The `failed_attempts` and `locked_until` columns on the user row. |
| Web sign-in sessions | `sajha/auth/__init__.py`, `sajha/auth/jwt_handler.py` | Stateless (JWT) | The `sajha_token` cookie holds a signed JWT and the user is reloaded from the database on each request. Every worker needs the same JWT secret (§5). |
| LLM token usage and daily budgets | `sajha/ai/llm/governed.py` (`TokenTracker`) | Shared | `llm:usage:<user>` and the daily counters `llm:daily:user:*` and `llm:daily:role:*`, which expire after 2 days. With the memory backend each factory keeps private counters, as before. |
| LLM response cache, provider health, provider circuit breakers | `sajha/ai/llm/governed.py` | Local | Caches and health probes. Each worker learning them on its own costs some duplicate calls, not correctness. |
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
| Federation upstream connections, pools, admission queues and breakers | `sajha/federation/` | Local, published | Each worker opens its own connections (a pool per upstream and replica) and bounds its own calls in flight. Each worker publishes its view of every upstream (state, connections, latency, load, last error, breaker) to `fed:health:<upstream>:<worker id>` with a TTL, reads every worker's view back, and opens its breaker when a peer opened its own (§4.9). The upstream list and approvals are in the federation store (storage backend); its revision, change lease and change announcements (`fed:store:*`, channel `fed:store`) are in the state store, so an approval reaches every worker at once and no worker writes a stale copy over it. An upstream's `max_calls_per_minute` window is in the state store. |
| SAJHA Net membership, catalogs, the host and tool table, contract quarantines, seen request nonces, assertion `jti`s, host-scoped tokens (hashed) | `sajha/net/node.py`, `sajha/net/integration/` | Shared | Keys under `sajhanet:<net>:` (`PrefixKV`). Each worker keeps its registry's proxies equal to the shared table. A nonce or `jti` seen on one worker is a replay on every other. |
| SAJHA Net gossip agent | `sajha/net/integration/__init__.py` | Shared (lease) | One worker per net holds the renewing lease `sajhanet:agent:<net>` (§4.7, TTL `sajhanet.agent_lease_seconds`) and runs that net's gossip; another takes over within one TTL. |
| SAJHA Net key directory | `sajha/net/integration/keystore.py` | Already shared (database) | The `sajhanet_api_keys` table. |
| SAJHA Net trust levels, blocks, user links and role maps, pins, runtime seeds, first-use keys, the CA's state, sponsored servers | `sajha/net/integration/` | Already shared (storage backend) | JSON documents under `sajhanet.data_dir` in the storage backend. |
| SAJHA Net saved peer list, keys and certificates | `sajha/net/membership.py`, `sajha/net/integration/__init__.py` | Local (disk) | Under `sajhanet.data_dir` on local disk, so a restart finds peers even when the storage backend is down; several hosts of one instance need the same key and certificate (the Helm chart's Secrets). |
| SAJHA Net per-peer circuit breakers and rate limits | `sajha/net/routing.py` | Shared when the state store is | `sajhanet.peer.shared` (`auto`): with a shared state store, one breaker per peer (`brk:<peer>`) and limits counted per calendar minute across workers (`rlout:`, `rlin:`, under `sajhanet:<net>:`); with `memory`, per process, so a per-peer limit allows up to N times its value with N workers. A breaker that cannot reach the store behaves as closed. |
| SAJHA Net tasks held at the host, cached remote results, 2025-11-25 sessions issued to members, visibility answers | `sajha/net/integration/tasks.py`, `catalogs.py`, `sajha/net/routing.py` | Shared | Host tasks are task records (`net:task:<net>/<instance>:`, the task record store, durable with `state.tasks.durable`); results kept by `sajhanet.cache.ttl_seconds`, sessions (`mcpsess:`) and visibility answers (`vis:`) are state-store keys under `sajhanet:<net>:` with TTLs. |
| SAJHA Net home's cache of host-scoped tokens, observed call paths | `sajha/net/integration/identity.py`, `sajha/net/routing.py` | Local | A token cache miss costs one exchange; call paths are what this process observed. |
| Log de-duplication sets, provider instances, glossary cache | `sajha/core/mcp_modern.py`, `sajha/core/mcp_apps.py`, `sajha/ai/llm/legacy.py`, `sajha/web/glossary.py` | Local | Process-local helpers that hold no client-visible state. |

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
- **Status notifications.** Every change of a task record is published on the change bus
  (section 4.5) under the task id. A `subscriptions/listen` stream on any worker that named
  the task re-reads the record and sends `notifications/tasks`.

### 4.5 Change bus

`ChangeBus.attach_store` (called at start-up for shared backends) publishes every event on
the `changes` channel as well, tagged with the bus's own origin. Events from other workers
go to this worker's `Subscription`s: listen streams, a 2025-11-25 session's `GET /mcp`
stream, legacy SSE and WebSocket pushes. Synchronous listeners stay local unless registered
with `add_listener(fn, remote=True)`; the only such listener is the workflow service, whose
event triggers therefore hear every worker's events. Task events never reach a listener. Each
publish carries an `id`, the same on every worker that receives it, and the workflow service
claims `wf:evclaim:<workflow>:<trigger>:<id>` before it fires, so one event starts one run
across all workers ([Workflows](Workflows.md#4-triggers)). Coalescing still applies per subscriber. A session's `GET /mcp`
stream lives on the worker that opened it, and the one-stream-per-session rule is enforced
per worker.

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

### 4.9 Federation upstream health

A connection to an upstream belongs to one worker's event loop, so connections, pools and the
admission queue stay per process. What other workers need is each worker's view: every
`federation.health.publish_seconds` (5 s) each worker writes one document per upstream,
`fed:health:<upstream>:<worker id>`, with a TTL of `federation.health.ttl_seconds` (30 s), and reads all
of them back with one `scan`. A worker that dies drops out when its documents expire. The breaker is
followed, not shared: a worker whose breaker is closed opens it when a peer published a breaker it
opened after its own failures, and from then on probes on its own after its recovery timeout, so one
worker's local network fault keeps the other workers off the upstream for at most one recovery
timeout. A followed breaker is published as followed and never followed in turn. The rules and the
switch (`federation.health.follow_peer_breakers`) are in
[Federation](Federation.md#gateway-scale).

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

- `python run_sajha_web.py --workers N` starts N uvicorn worker processes. In that mode the
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
  `/health` reports `state.reachable: false` meanwhile. Sessions and other records written
  before the outage are there when Redis returns.
- **Shared store unreachable at start-up** (redis or database). Start-up stops ("refusing to
  start") and the process exits non-zero (§6), so the deployment fails visibly.
- **Database backend unavailable at runtime.** State-store operations raise rather than fall
  back, and the rows written before are there when the database is reachable again.
- **A worker dies mid-task.** Its tasks stay `working` until its heartbeat expires (up to
  30 s), then any worker that reads one marks it `failed` with -32603 (§4.4); it is never re-run.
- **A federated upstream breaks.** Its tools stay listed and calls fail fast; after the
  breaker's `failure_threshold` failures it opens and calls stop reaching the upstream, and
  after `recovery_timeout` one probe call closes it again once the upstream answers
  ([Federation](Federation.md)).
- **Database connections and concurrent calls.** The rule: a database connection is held for
  the shortest time the work needs. One session per unit of work, given back to the pool as soon
  as the database part is done, and always closed or rolled back when the work raises
  (`sajha/db/engine.py`: `get_db` for a request, `session_scope()` for services, tools and
  background jobs, `release_session` and `AuthContext.release_db` to give a request's connection
  back early). A session checks a connection out at its first query and keeps it until it is
  closed; held across a tool call, a model call, a federated call or an open stream, one
  connection per call in flight was tied up, and in the release before this change `/mcp` froze at
  16 concurrent calls (the pool's 15 connections on SQLite were gone and the next request's
  authentication, on the event loop, blocked the whole worker for the pool's 30 s timeout). What
  the code does now:
  - *Requests give the connection back before slow work.* `get_current_user`, behind every
    signed-in page and API route, releases it once the caller is known; the MCP endpoints
    (`authorize_mcp`) look the caller up, build their identity and tool policy and release the
    connection, all in the thread pool, before the call runs or a stream opens; the
    OpenAI-compatible endpoint after its key check; the REST tool endpoint and A2A before the tool
    runs and again after their own writes. `AuthContext.has_permission` reads the roles'
    permissions that were loaded then, in memory, so it checks nothing out.
  - *No database wait on the event loop.* Authentication on `/mcp`, `/mcp/message`, the legacy SSE
    stream, the WebSocket transport, `/oauth/authorize`, `/oauth/token` and the SSO callback runs
    in the thread pool (`run_in_threadpool`), and so do the tool and shell work of the contract-test
    and shell routes. Routes whose whole body is database work are plain `def` handlers, which
    FastAPI runs in the thread pool. A route that must read its request body first (an `async def`)
    reads it, then runs its database part with `run_in_threadpool` (key and user administration,
    sign-in and password changes, provider and model edits, composite tools, the credential files,
    A2A tasks, the REST tool endpoint's usage row, the catalog routes' tool policy). No `async`
    route in `sajha/routes/` makes a database call on the event loop.
  - *A dry pool answers at once.* A checkout waits at most `db.pool.timeout_seconds` (5 s), then
    the request is shed: HTTP 503 with `Retry-After: 1`; on `/mcp` a JSON-RPC error, code `-32000`,
    `data: {reason: "db_pool_exhausted", retryable: true, retryAfterSeconds: 1}`. It is never a hang,
    and never a 401 (authentication passes a pool timeout through instead of treating the key as
    unknown). Each one counts in `sajha_db_pool_exhausted_total`; the pool's gauges and every
    worker's pool on the System monitor page are in [Observability](Observability.md) §2.2.
  - *The state store has a pool of its own.* With `state.backend: database` on SAJHA's database,
    the store opens its own small pool (`state.database.pool_size`, default 3, plus at most 2
    overflow), so its calls made on the event loop (session lookups, rate-limit counters) never
    wait behind request threads for a connection.
  - *Guards.* `tests/test_db_session_hold.py` reads every async route in `sajha/routes/` and fails
    when one holds a database session across an `await` without releasing it, and, stricter, when any
    `async def` there (a route or an async helper it awaits) makes a database call on the event loop at
    all: a DAO or session method called with the request's session or `AuthContext._db`, or a session
    opened (`session_scope()`, `get_db_session()`), outside `await run_in_threadpool(...)`. Both are
    AST checks with explicit, commented allowlists, empty today; a database call hidden inside a
    synchronous helper that opens its own session is not visible to them. `tests/test_db_pool.py` drives a one-connection
    pool: a dry pool answers 503 fast on `/mcp` and the REST endpoint while `/health` answers, and
    a tool that raises, a route that raises after a database read and a client that disconnects
    mid-request all leave the checked-out count at its baseline. `tests/test_failure_behaviour.py`
    runs more slow calls than the pool holds on three endpoints at once, and 128 concurrent
    `tools/call` requests per era against one worker with a two-connection pool (every answer a
    success or a 503, none hung, `/health` alive).

  **Sizing the pool.** Per worker, a connection is needed only while a thread is inside a query,
  and the threads that touch the database are bounded by the thread pool (AnyIO's default 40
  tokens) plus the background jobs, so `db.pool.size` 10 with `db.pool.max_overflow` 10 (the
  defaults: overflow -1 means "as many as the size") serves hundreds of concurrent calls; §9
  measures it. On PostgreSQL every worker opens its own pools, so keep

  ```
  workers × (db.pool.size + max_overflow + state pool, 5 with state.backend: database)  +  other clients
      ≤  max_connections − a reserve for administration
  ```

  (four workers with the defaults: 4 × (10 + 10 + 5) = 100, PostgreSQL's default
  `max_connections`, so raise it or lower the pool). Raise `db.pool.size` when
  `sajha_db_pool_waiting` is often above zero or `sajha_db_pool_exhausted_total` grows; add workers
  (or hosts) when the CPU of each worker is the limit, which is what §9 shows. **SQLite** is for one
  machine and light load: its file takes one writer at a time (WAL lets readers go on; SAJHA sets
  `journal_mode=WAL`, `synchronous=NORMAL` and a 30 s `busy_timeout`, and gives the file the same
  kind of pool). **PostgreSQL** is for real concurrency: several workers, pods or hosts, and write
  traffic ([Database Setup](../getting-started/Database%20Setup.md)).
- **Database backend latency.** Pub/sub is a polled table, so change notifications and
  task cancels arrive one poll interval late (500 ms by default). Event rows are deleted
  after a minute.
- **Blocking calls.** State-store calls are synchronous, and some are made on the event
  loop. With Redis or a local database they take well under a millisecond to a few
  milliseconds. A remote PostgreSQL adds its round-trip time. With the database backend they use
  the store's own pool (above), so they never queue behind request threads.
- **A stream belongs to one worker.** An open SSE or WebSocket stream lives where it was
  opened. Only the messages that must reach it are relayed. If that worker dies, the stream
  ends and the client reconnects, as it would after a restart.
- **SQLite on several hosts** is not supported. Use PostgreSQL or Redis.
- **SAJHA Net on `memory`.** Each worker would run its own gossip agent and keep its own
  membership, nonces and host and tool table, so an instance with several workers in a net needs
  `redis` or `database`. Its per-peer breakers and rate limits stay per process (§3).

## 8. Tests

- `tests/test_state_store.py` runs the store contract, and every migrated component with
  two instances standing for two workers, against memory, fakeredis (when `fakeredis` and
  `lupa` are installed), a real Redis (`SAJHA_TEST_REDIS_URL`, skipped when none answers)
  and SQLite.
- `tests/test_state_multiworker.py` starts two real server processes that share one
  database and backend (database, and redis when available). It checks over HTTP that a
  code issued by A is redeemed by B, a task created on A is read and cancelled on B, sign-in
  failures add up across workers, and an event on A reaches a `subscriptions/listen` stream
  on B. It also starts `run_sajha_web.py --workers 2` and checks that both workers report the
  shared backend.
- `tests/test_federation_scale.py` runs two federation managers standing for two workers on the
  memory, fakeredis and SQLite stores: the shared upstream view, a breaker followed from a peer and
  probing on its own, a view expiring with its TTL.
- `tests/test_failure_behaviour.py` (marker `failure`) asserts the behaviour of §7: an
  unreachable redis or database store stops start-up with a non-zero exit; Redis lost at run
  time (fakeredis with its connection cut) fails a new 2025-11-25 session with HTTP 500, reports
  `reachable: false` and recovers; the database store raises while its file's folder is gone and
  keeps its rows; two real servers on one SQLite state database, one killed with SIGKILL during a
  task, and the other reports the task `failed` with -32603 once the heartbeat is gone (the test
  deletes the heartbeat key instead of waiting out its TTL); a federated upstream stopped and
  restarted opens and closes its breaker; the request's database session is closed once the
  identity is known; more slow calls than the pool holds complete on three endpoints at once; and 128
  concurrent `tools/call` requests per era against one real worker with a two-connection pool are each
  a success or a 503 with `Retry-After`, none hung, with `/health` answering throughout. Each test has
  its own scratch folder, key prefix and ports, and bounded waits.
- `tests/test_db_pool.py` checks the pool settings and their validation, the counting pool on a SQLite
  file, the `DB_*` switch, the 503 of a dry pool, connections returned on error paths, and the pool on
  the System monitor; `tests/test_db_session_hold.py` is the static guard of §7.
- `tests/test_state_lease.py` runs the lease contract (exclusive and re-entrant claim,
  renewal only by the holder, expiry and takeover, release, one-slot claims, a race of
  six claimants, the `Lease` keeper's renewal and loss) on the same backends; the real
  Redis case is skipped when no server answers at `SAJHA_TEST_REDIS_URL`.

## 9. Measured performance

These are evidence of one run on one machine, not promises: rerun the harness on your own hardware
before sizing a deployment. The load generator shares the machine with the server, so absolute numbers
are lower than on a dedicated host; compare rows with each other.

### MCP endpoint

`tools/bench/bench.py` (standard library and httpx) starts `run_sajha_web.py` for each configuration (a
database and state backend, and a worker count) on a local port with a scratch database, scratch
credential files and a scratch API key, waits until `/health` has answered from every worker, and drives
`/mcp` from several load processes (asyncio and httpx) that keep a fixed number of requests in flight: a
warm-up, unmeasured, then a measured window. Modern requests are MCP 2026-07-28 (stateless, `_meta` on
every request); legacy clients run `initialize` once and send their requests on that `Mcp-Session-Id`
(2025-11-25). The call is `calc_future_value`, a calculator that runs in the process with no network, with
new arguments every time so the tool cache never answers. A non-200 answer, a JSON-RPC error or a tool
result with `isError` is an error, not a latency sample; a 503 with `Retry-After` (a dry database pool,
§7) is counted apart as shed; a request with no answer within the bound is hung. The output is a JSON file
and a markdown table, with the CPU, cores, RAM, OS, Python, SAJHA version and commit, the load average
before the run and before each row, and the reasons for any errors.

Two scenarios. The standard one runs `tools/list` and `tools/call` on both eras at one level (32 in flight
by default) on `memory`, `database` (SQLite) and `redis` (skipped when no server answers). The high
concurrency one (`--scenario highconc`) runs `tools/call` on both eras at 64, 256 and 512 requests in
flight, on SQLite and PostgreSQL at 1 and 4 workers (the state store on the same database:
`state.backend: database`), probes `/health` every half second during each row, and passes or fails the
run: no request unanswered or slower than 30 s, `/health` answering within 5 s throughout, errors (shed
requests excluded) at most 1%. PostgreSQL rows run only when `SAJHA_BENCH_PG_URL` names a server: each
configuration gets a scratch database built from SAJHA's two schema files and dropped afterwards, and the
URL is never printed. `tests/test_failure_behaviour.py` runs a bounded version in the suite (128 in flight,
one worker, a two-connection pool).

Run of 2026-10-11 (high concurrency): AMD Ryzen AI 9 HX 370 w/ Radeon 890M, 24 logical cores, 60.8 GB RAM,
Linux 7.1.5 (glibc 2.43), Python 3.14.4, SAJHA 8.11.0 at commit `3e72309` with this release's changes
uncommitted, PostgreSQL 17 in a local container. Default pool (`db.pool.size` 10, overflow 10, 5 s
checkout timeout). 4 load processes on the same machine; 2 s warm-up and 10 s measured per row. The
one-minute load average was 2.0 at the start and 8.0 at the end: the server workers and the load
processes themselves account for most of it, and other jobs ran on the machine too (the "Load avg" column
is the value before each row). Verdict: **pass**, every row.

| Database | Workers | Era | In flight | Requests | Shed (503) | Errors | Hung | Throughput (req/s) | p50 (ms) | p99 (ms) | Slowest (ms) | /health max (ms) | Load avg |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SQLite | 1 | modern (2026-07-28) | 64 | 2956 | 0 | 0 | 0 | 295.6 | 199.08 | 395.99 | 648.76 | 178.57 | 2.02 |
| SQLite | 1 | legacy (2025-11-25) | 64 | 3352 | 0 | 0 | 0 | 335.2 | 175.98 | 352.04 | 364.63 | 204.51 | 2.6 |
| SQLite | 1 | modern (2026-07-28) | 256 | 2757 | 0 | 0 | 0 | 275.7 | 795.06 | 1319.61 | 1371.81 | 1533.7 | 2.31 |
| SQLite | 1 | legacy (2025-11-25) | 256 | 3134 | 0 | 0 | 0 | 313.4 | 776.64 | 1268.89 | 1296.49 | 1694.39 | 2.34 |
| SQLite | 1 | modern (2026-07-28) | 512 | 2306 | 0 | 0 | 0 | 230.6 | 1785.71 | 2024.63 | 2093.27 | 992.53 | 2.48 |
| SQLite | 1 | legacy (2025-11-25) | 512 | 2251 | 0 | 0 | 0 | 225.1 | 1551.28 | 7067.77 | 8472.67 | 3243.3 | 3.37 |
| SQLite | 4 | modern (2026-07-28) | 64 | 12061 | 0 | 0 | 0 | 1206.1 | 48.12 | 287.76 | 456.54 | 60.73 | 5.21 |
| SQLite | 4 | legacy (2025-11-25) | 64 | 8135 | 0 | 0 | 0 | 813.5 | 51.67 | 354.55 | 2306.33 | 30.99 | 5.57 |
| SQLite | 4 | modern (2026-07-28) | 256 | 8865 | 0 | 0 | 0 | 886.5 | 271.42 | 630.35 | 862.11 | 182.56 | 5.29 |
| SQLite | 4 | legacy (2025-11-25) | 256 | 4862 | 0 | 0 | 0 | 486.2 | 255.2 | 3522.55 | 3891.13 | 183.19 | 5.11 |
| SQLite | 4 | modern (2026-07-28) | 512 | 7096 | 0 | 5 | 0 | 709.6 | 434.97 | 3057.8 | 5606.64 | 820.81 | 6.98 |
| SQLite | 4 | legacy (2025-11-25) | 512 | 5779 | 0 | 4 | 0 | 577.9 | 434.02 | 3912.36 | 3943.69 | 944.12 | 6.97 |
| PostgreSQL | 1 | modern (2026-07-28) | 64 | 2658 | 0 | 0 | 0 | 265.8 | 228.86 | 457.99 | 496.19 | 58.52 | 6.22 |
| PostgreSQL | 1 | legacy (2025-11-25) | 64 | 2676 | 0 | 0 | 0 | 267.6 | 231.97 | 404.0 | 425.73 | 122.7 | 6.06 |
| PostgreSQL | 1 | modern (2026-07-28) | 256 | 2447 | 0 | 0 | 0 | 244.7 | 965.49 | 1080.68 | 1122.35 | 950.05 | 6.25 |
| PostgreSQL | 1 | legacy (2025-11-25) | 256 | 2619 | 0 | 0 | 0 | 261.9 | 975.61 | 1200.75 | 1256.29 | 1792.19 | 5.16 |
| PostgreSQL | 1 | modern (2026-07-28) | 512 | 2206 | 0 | 0 | 0 | 220.6 | 1886.19 | 2219.55 | 2278.41 | 342.25 | 5.05 |
| PostgreSQL | 1 | legacy (2025-11-25) | 512 | 2614 | 0 | 0 | 0 | 261.4 | 1959.8 | 2152.57 | 2180.25 | 3048.18 | 4.51 |
| PostgreSQL | 4 | modern (2026-07-28) | 64 | 9008 | 0 | 0 | 0 | 900.8 | 64.16 | 182.05 | 570.24 | 502.75 | 3.85 |
| PostgreSQL | 4 | legacy (2025-11-25) | 64 | 8371 | 0 | 0 | 0 | 837.1 | 70.88 | 167.12 | 478.99 | 353.07 | 4.69 |
| PostgreSQL | 4 | modern (2026-07-28) | 256 | 8174 | 0 | 0 | 0 | 817.4 | 283.45 | 663.08 | 756.55 | 133.25 | 5.84 |
| PostgreSQL | 4 | legacy (2025-11-25) | 256 | 7725 | 0 | 0 | 0 | 772.5 | 307.33 | 675.75 | 812.78 | 194.54 | 6.61 |
| PostgreSQL | 4 | modern (2026-07-28) | 512 | 6282 | 0 | 2 | 0 | 628.2 | 543.93 | 2869.93 | 4835.43 | 907.76 | 7.21 |
| PostgreSQL | 4 | legacy (2025-11-25) | 512 | 6497 | 0 | 2 | 0 | 649.7 | 504.49 | 4807.96 | 6239.77 | 765.65 | 7.35 |

What the rows show. The freeze is gone: 512 calls in flight against one worker with a pool of 20
connections complete, none hung, none shed, where the release before froze at 16 (§7). No row shed a
request: connections are held for milliseconds, so the pool never ran dry. One worker is bound by one
Python process (about one core): throughput stays near 230 to 330 calls per second whatever the level,
and latency grows with the queue (512 in flight at about 230 per second is about 2 s each); `/health`
waits in the same queue and stayed within 3.3 s. Four workers carry two and a half to four times as much at 64 in
flight, less as the level rises, because the load processes and the workers share the 24 cores. SQLite
and PostgreSQL perform alike here (PostgreSQL local, so no network round trip; the writes per call are
an audit record and a usage row). At 512 in flight on four workers a few requests (at most 5 per row,
0.1%) failed with `ReadError`: the worker's event loop lagged by seconds and uvicorn's 5 s keep-alive
timer closed a connection the client was about to reuse; a client retries those. More workers or hosts,
not a larger pool, raise throughput.

Reproduce:

```
.venv/bin/python tools/bench/bench.py --scenario highconc --out /tmp/sajha-bench    # SQLite rows
SAJHA_BENCH_PG_URL=postgresql://user:password@host:5432/postgres \
    .venv/bin/python tools/bench/bench.py --scenario highconc --out /tmp/sajha-bench    # and PostgreSQL
.venv/bin/python tools/bench/bench.py --configs memory:1,database:1,database:4,redis:1,redis:4 \
    --duration 20 --warmup 3 --out /tmp/sajha-bench                                    # standard
```

### Federation

`tools/bench/bench_federation.py` starts the example upstream (`sajha/examples/federation/units_server.py`)
and, for each configuration, a SAJHA server with that upstream configured twice (once unbounded, once
with `max_in_flight: 4` and no queue), and drives MCP 2026-07-28 `tools/call` with 32 requests in flight
from 4 load processes: a local tool (`calc_future_value`, the baseline), a proxied tool
(`units__celsius_to_fahrenheit`), and a proxied tool that takes about 100 ms upstream
(`unitsbounded__countdown`) to show shedding. It reuses the server start-up of `tools/bench/bench.py`.

Run of 2026-10-11, measured earlier than the MCP endpoint run above (before the connection changes of
§7): AMD Ryzen AI 9 HX 370, 24 logical cores, 60.8 GB RAM, Linux, Python 3.14.4, SAJHA 8.11.0 with the
gateway-scale changes uncommitted; 2 s warm-up and 10 s measured per row, on a machine other jobs were
using at the same time.

| Backend | Workers | Pool | Phase | Requests | Shed | Errors | Throughput (req/s) | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| memory | 1 | 1 | local | 4024 | 0 | 0 | 402.4 | 67.56 | 128.04 | 297.46 |
| memory | 1 | 1 | proxied | 1661 | 0 | 0 | 166.1 | 177.99 | 285.58 | 584.34 |
| memory | 1 | 1 | shed | 286 | 1983 | 0 | 28.6 | 224.74 | 363.56 | 719.2 |
| memory | 1 | 4 | local | 3603 | 0 | 0 | 360.3 | 84.13 | 123.24 | 255.08 |
| memory | 1 | 4 | proxied | 2579 | 0 | 0 | 257.9 | 116.89 | 158.56 | 391.94 |
| memory | 1 | 4 | shed | 311 | 3247 | 0 | 31.1 | 187.33 | 237.58 | 617.8 |
| database | 4 | 1 | local | 11040 | 0 | 0 | 1104.0 | 27.33 | 42.9 | 78.78 |
| database | 4 | 1 | proxied | 7019 | 0 | 0 | 701.9 | 42.82 | 69.79 | 94.34 |
| database | 4 | 1 | shed | 1336 | 8710 | 0 | 133.6 | 123.37 | 163.87 | 528.86 |

What the rows show: with one worker and one connection, a proxied call costs about two and a half times
a local one under this load, because every call to the upstream goes through one connection on the
federation event loop; four pooled connections raise proxied throughput by about half (166 to 258
requests per second) and cut the tail. Four workers multiply both. The shed rows hold the bounded
upstream at its limit (4 calls in flight per worker: about 40, and with four workers about 160, calls
per second of 100 ms each, less overhead) and refuse the rest at once without errors; the "Shed" column
counts those refusals.

Reproduce:

```
.venv/bin/python tools/bench/bench_federation.py --configs memory:1:1,memory:1:4,database:4:1 \
    --duration 10 --warmup 2 --out /tmp/sajha-bench
```

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
