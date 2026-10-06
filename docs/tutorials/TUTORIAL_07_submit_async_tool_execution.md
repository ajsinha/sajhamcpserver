# Tutorial 7: Submit Async Tool Execution

Run a tool in the background and have SAJHA deliver the result to a webhook or a file, instead of holding the HTTP request open.

## What you'll learn

- How to submit a tool for background execution
- How to choose a delivery target
- How to poll, cancel and retry tasks, from the API and the admin UI

## Prerequisites

- A running server and a JWT as `$TOKEN` ([Tutorial 1](TUTORIAL_01_getting_started.md), step 8). Submitting needs the admin role or a role permission with resource type `async` and action `execute`, plus execute access to the tool itself; the admin page needs the admin role.

## How it works

`POST /api/tools/<name>/execute-async` queues the call and returns a `task_id` right away. A pool of background workers runs the tool through the same path as a normal call, so caching, the circuit breaker and metrics all apply. The worker then delivers a JSON payload with `task_id`, `tool_name`, `status`, `result`, `error`, `arguments`, `duration_ms` and `timestamp`. If the queue is full, the endpoint answers `503`. Tasks are held in the memory of the worker that queued them, and are lost when the server restarts. With a shared `state.backend`, every worker can read, list and cancel them ([Scaling and State](../architecture/Scaling%20and%20State.md)).

## Steps

### 1. Build the request body

Put the tool's arguments at the **top level** of the JSON body, next to an `async` block:

| `async` field | Meaning |
|---------------|---------|
| `delivery` | `webhook` or `file` |
| `destination` | Required. A URL for `webhook`. A path for `file`: relative paths go under `data/async_results/`. |
| `headers` | Optional. Extra HTTP headers for `webhook` delivery. |

### 2. Submit

File delivery:

```bash
curl -s -X POST http://localhost:3002/api/tools/calc_percentage_change/execute-async \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"old_value": 1, "new_value": 3,
       "async": {"delivery": "file", "destination": "tutorial/result.json"}}'
# -> {"task_id": "t-4e5b18c8db5b", "status": "queued", "tool_name": "calc_percentage_change",
#     "delivery": "file", "destination": "tutorial/result.json",
#     "poll_url": "/api/async/tasks/t-4e5b18c8db5b"}
```

Webhook delivery is the same request with `"async": {"delivery": "webhook", "destination": "https://example.com/hooks/sajha"}`. The destination must start with one of the URL prefixes in `async.delivery.webhook.allowed_urls` (empty by default, which refuses every webhook) and resolve to a public address unless `allow_private_networks` is true. SAJHA POSTs the payload with an `X-Sajha-Task-Id` header. If the endpoint doesn't return a 2xx status, SAJHA retries up to 3 times with backoff.

### 3. Poll the task

```bash
curl -s http://localhost:3002/api/async/tasks/t-4e5b18c8db5b -H "Authorization: Bearer $TOKEN"
# -> {"status": "delivered", "delivery_status": "success", "duration_ms": 1.1,
#     "result": {"old_value": 1, "new_value": 3, "percentage_change": 200.0}, ...}
```

A task moves through `queued` → `running` → `completed` or `failed`. After a successful delivery its status becomes `delivered`. With file delivery, the payload is now at `data/async_results/tutorial/result.json`.

Other endpoints:

| Method and path | Purpose |
|-----------------|---------|
| `GET /api/async/tasks?status=failed&limit=50` | List tasks, with executor stats |
| `GET /api/async/stats` | Executor stats only |
| `POST /api/async/tasks/<id>/cancel` | Cancel a **queued** task |
| `POST /api/async/tasks/<id>/retry` | Re-submit a **failed** or **cancelled** task as a new task |

### 4. Monitor in the UI

**Admin → Async tasks** (`/admin/async-tasks`) lists tasks with counters and a status filter. Queued tasks have a cancel button; failed and cancelled tasks have a retry button.

> **Kafka:** A third delivery type, `kafka`, publishes to the topic named in `destination` on `async.delivery.kafka.bootstrap_servers`; it needs the `confluent-kafka` package. Worker count, queue size, retention and the delivery settings are under `async:` in the [Configuration Reference](../getting-started/Configuration%20Reference.md#async-and-shell).

> A task is delivered even when the tool fails. A successful delivery sets its status to `delivered`, so check the `error` field as well as `status`.

## What next

- [API Reference](../protocol/API%20Reference.md)
- [MCP Protocol Guide](../protocol/MCP%20Protocol%20Guide.md): MCP-native long-running calls (tasks extension, 2026-07-28)
- Next tutorial: [Custom Configuration](TUTORIAL_08_custom_configuration.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
