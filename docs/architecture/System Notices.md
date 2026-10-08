# System Notices

A **system notice** is SAJHA telling the people who run it that something needs attention: the
database schema is out of date, a circuit breaker is open, a scheduled workflow keeps failing, a
model alias has nothing to run on, a federated server is unreachable. Such conditions are also
written to the log, counted in metrics or sent by alert rules ([Observability](Observability.md)
section 5); notices are the place in the console that shows what is wrong right now. One service
(`sajha/notices/`) takes reports from every subsystem; the console shows them as a banner, a
dashboard panel and a navbar badge; administrators acknowledge and clear them.

Later waves of the [Implementation Plan](Implementation%20Plan.md) add their own sources (LLM
tools in wave 2, SAJHA Net in wave 4); section 4 lists the ones built so far.

---

## 1. What a notice is

| Field | Meaning |
|---|---|
| `id` | Stable identity of the condition, chosen by the source: `<source>.<condition>[:<subject>]`, for example `federation.upstream_down:github`. Raising the same id again refreshes that notice instead of adding a second one. |
| `severity` | `info`, `warning`, `error` or `critical` |
| `source` | The subsystem that raised it (`db`, `resilience`, `workflows`, `llm`, `federation`, `alerts`, ...) |
| `title` | One line, written for an operator |
| `detail` | What happened, what it affects, and what to do, in a few sentences |
| `link` | The console page that shows or fixes it |
| `since`, `last_seen` | When the condition started and was last confirmed (epoch seconds) |
| `audience` | `admin` (default) or `everyone`, for conditions every signed-in user should know about (a federated server that hosts tools they use being down) |
| `state` | `active`, `acknowledged` or `cleared` |
| `acknowledged_by`, `acknowledged_at` | Who acknowledged it, if anyone |
| `cleared_at`, `cleared_reason` | When and why it cleared: `source` (the condition ended), `ttl`, `admin`, `evicted`, or the source's own reason |

Administrators also see `ttl_minutes` and `workers` (how many workers currently hold the
condition; see section 2).

## 2. Lifecycle

- **Raised** by a source when its condition starts, with a stable id.
- **Refreshed** while the condition holds: `last_seen` moves; the title, detail or severity may
  change. A refresh is not an audit event; a change of severity is. A notice that becomes **more
  severe** than when it was acknowledged becomes `active` again.
- **Cleared** when the source reports the condition has ended, or when nobody has refreshed it
  for its ttl (`notices.default_ttl_minutes`, or the source's own; `0` = never), so a source that
  dies cannot leave a stale notice forever. Raising a cleared id starts a new occurrence.
- **Acknowledged** by an administrator: it leaves the banner and the badge and stays on the
  status panel until it clears. Acknowledgement never hides a `critical` notice from the banner.
- **Cleared by an administrator** (API or script): useful for a notice whose source is gone; a
  source whose condition still holds raises it again at its next check.
- **Every transition is an audit event** (`notice.raised`, `notice.escalated`, `notice.changed`,
  `notice.updated`, `notice.acknowledged`, `notice.cleared`, through `sajha/core/audit.py`, so
  also in the [hash chain](Policy%20and%20Audit.md)), kept under the audit log's retention.

**Shared by every worker.** Notices live in the state store (`notice:<id>`, one entry per id;
`state.backend`, see [Scaling and State](Scaling%20and%20State.md)), so every worker sees the same
set; each change is an atomic update, so exactly one worker records (and forwards) a transition.
Some conditions are judged per process (circuit breakers, provider health, upstream
connections): their sources raise with `holder=<worker id>`, and the notice clears only when no
worker still holds it, so one worker's healthy breaker does not clear another's open one. With
`state.backend: memory` each worker has its own notices, as for everything else in that store.

**Bounded.** At most `notices.max_active` notices are open. A new one beyond that clears the
oldest open notice of the lowest severity (reason `evicted`), or is dropped when every open
notice is more severe. Cleared notices are kept for `notices.cleared_retention_minutes`.

## 3. Where they appear

| Place | Shows |
|---|---|
| **Banner** on every console page | The most severe open notice the viewer may see that is unacknowledged (or `critical`) and at least `notices.banner_min_severity` (`error` by default), with a count of the viewer's other open notices and a link to the status panel. `role="alert"`. |
| **System status panel** on the dashboard (`/dashboard#system-status`) | Every open notice the viewer may see, grouped by severity, with source, since, last seen, detail and link; an Acknowledge button for administrators on active ones; a toggle to show recently cleared ones. |
| **Navbar badge** | The number of the viewer's open notices at `warning` or above that are unacknowledged (or `critical`). It sits outside the collapsed menu, so it shows on phones; hidden at zero. |
| **API** | Section 5. |
| **Alert channels** | A notice of a chosen severity is also sent through an alert channel (`notices.forward`); and an alert rule can raise a notice through the `notice` channel, so existing rules appear in the console too (section 4). |

Who sees what: administrators see every notice; other signed-in users see only notices with
audience `everyone`; signed-out pages show nothing.

The banner and panel follow the console's conventions: severity in words as well as colour (the
word is always printed, `critical` is a filled label), colours only from the theme tokens so all
four themes work, phone-width layouts, and keyboard-reachable actions whose names say which notice
they act on. The page is kept current by server-sent events from `/api/notices/stream` (the
stream sends the viewer's view whenever any notice changes; the browser falls back to polling
`/api/notices` every minute if the stream fails), so a notice appears and disappears without a
reload. Files: `sajha/web/templates/common/_notices_banner.html`, `_notices_badge.html`,
`sajha/web/templates/dashboard/_system_status.html`, `static/css/notices.css`,
`static/js/notices.js`.

## 4. Sources

Each source owns the ids under its prefix and clears them when its condition ends. Polled
sources are re-checked by a watcher thread every `notices.check_interval_seconds` (and once at
start-up), which also clears notices whose ttl has passed.

| Source | Id | Severity | Raised when | Cleared when |
|---|---|---|---|---|
| Database (`sajha/db/schema.py`) | `db.schema` | `warning` | The start-up schema check (with `db.schema_check: warn`) finds missing tables, columns or indexes; the detail carries the SQL to run | A later start-up finds nothing missing |
| Resilience (`sajha/core/circuit_breaker.py`) | `resilience.breaker_open:<breaker>` | `warning` | A breaker opens: tool providers, federated upstreams, LLM providers (`llm:<provider>`); raised at the transition and confirmed by the watcher; per worker | The breaker closes |
| Workflows (`sajha/workflows/service.py`) | `workflows.scheduled_failing:<workflow>` | `error` | Scheduled (cron) runs of the workflow failed `notices.workflow_failures` times in a row (no ttl) | A scheduled run succeeds, or the workflow is disabled or deleted |
| Intelligence layer | `llm.alias_unavailable:<alias>` | `error` for `default`, else `warning` | The alias resolves to no available candidate; per worker | It resolves again |
| Intelligence layer | `llm.provider_down:<provider>` | `warning` | An active provider's health check says it is down; per worker | It is healthy again |
| Federation | `federation.upstream_down:<upstream>` | `error`; audience `everyone` when the upstream has approved items | An enabled upstream is in error (or still connecting after an error); per worker | It connects, or is disabled |
| Federation | `federation.approvals:<upstream>` | `warning` | Tools from the upstream are new or changed and wait for an administrator's approval | None is waiting |
| Federation | `federation.sign_in:<upstream>` | `warning` | The upstream answered HTTP 401 with no credential configured: it needs per-user OAuth sign-in, not supported yet ([Federation](Federation.md#the-mcpservers-file)) | It connects |
| Federation | `federation.mcp_servers` | `warning` | Entries of the mcpServers file are invalid, duplicate a `federation.upstreams` id or clash on a prefix | The file loads cleanly |
| Federation | `federation.mcp_servers.raw_secrets` | `info` | The mcpServers file holds raw credential headers (names listed, never values) | They are `${NAME}` references or gone |
| Tools registry (`sajha/tools/tools_registry.py`) | `tools.reserved_name:<tool>` | `error` | A tool that is not namespaced has `__` in its name and is refused ([Federation](Federation.md#names)) | Never by itself: rename the tool; an administrator clears it |
| Alert rules (`sajha/observability/alerts.py`) | `alerts.rule:<rule>` | the channel's `severity` (default `warning`) | A rule with `channel: {type: notice}` holds at an evaluation; per worker | It stops holding |
| LLM tools (`sajha/ai/llm_tools/runtime.py`) | `llm_tools.memory` | `warning` at the soft limit, `error` at the hard one | The memory guard passes its soft or hard resident-memory limit (`ai.llm_tools.runtime.memory_guard`); per worker; ttl 10 minutes | Resident memory falls below the soft limit |
| LLM tools | `llm_tools.busy` | `warning` | A run is refused as `busy` (queue full, queue timeout, hard memory limit); per worker; ttl 10 minutes | The ttl passes with no further refusal |
| LLM tools | `llm_tools.spool_full` | `warning` | A payload could not be spooled because `ai.llm_tools.memory.spool.max_mb` or `per_run_mb` is reached (it was truncated instead); per worker; ttl 30 minutes | The next payload is spooled |
| Credentials (`sajha/auth/credential_jobs.py`) | `auth.plain_credentials` | `warning` | `auth.credential_storage` is `plain` (the shipped default; [Security Model](../security/Security%20Model.md#credential-storage-and-files)); no ttl | The setting is `hashed` (checked at start-up and when the users file changes) |
| Credentials | `auth.test_admin_key` | `critical` | A usable `test_admin` record exists in `config/apikeys.json` while `sajhanet.test_admin_key.enabled` is on; it also signs SAJHA Net calls ([Security Model](../security/Security%20Model.md#test-admin-key)); no ttl | The switch is off or no usable record remains |
| Credentials | `auth.users_file` | `error` | Users in `config/users.json` could not be applied (an unknown role, a missing password); no ttl | The file applies cleanly |
| Credentials | `auth.apikeys_dump` | `warning` | Writing `config/apikeys_db.json` failed; no ttl | The next dump succeeds |
| SAJHA Net (`sajha/net/integration/`) | `sajhanet.not_joined:<net>` | `error`; `info` for a net of one | The net is not joined: no seed or saved peer answers, a configuration error, no acceptable address; for a net of one, it has no certificate yet ([SAJHA Net](SAJHA%20Net.md#66-restarts)); no ttl | The server joins the net |
| SAJHA Net | `sajhanet.name_conflict:<net>` | `error` | Every member refuses this server under a held name; no ttl | It joins (its configuration or certificate changed) |
| SAJHA Net | `sajhanet.name_conflict_seen:<net>:<claimant>` | `warning` | Another participant claimed a held name and was refused; ttl 60 minutes | The ttl passes |
| SAJHA Net | `sajhanet.self_seen:<net>` | `warning` | A member record that is this server under another name or key; ttl 600 minutes | The ttl passes |
| SAJHA Net | `sajhanet.member:<net>:<member>` | `warning` | A member is `suspect`, `left` or `dead` (no ttl for `dead`) | It is `alive` again, or leaves retention |
| SAJHA Net | `sajhanet.certificate:<net>` | `warning`, `error` once expired | This server's certificate is in the last third of its validity, or expired; no ttl | It is renewed |
| SAJHA Net | `sajhanet.renewal:<net>` | `warning` | Renewal at the CA keeps failing | It is renewed |
| SAJHA Net | `sajhanet.revocations:<net>` | `warning` | A member holds a newer revocation list that could not be fetched | A newer list arrives |
| SAJHA Net | `sajhanet.ca_created:<net>` | `warning`; audience `admin`; ttl a week | A net of one created its CA at first start: back up the key | The ttl passes |
| SAJHA Net | `sajhanet.default_name` | `info` | A net is still named `default` (raised at start-up); no ttl | An administrator clears it after naming the net |
| SAJHA Net | `sajhanet.plain_http:<net>` | `warning` | `require_https` is off for the net (raised at start-up); no ttl | An administrator clears it after turning HTTPS back on |
| SAJHA Net | `sajhanet.peer_added:<net>:<url>` | `info`, `warning` on failure | An administrator pointed this server at a peer by address; ttl a day | The ttl passes |
| SAJHA Net | `sajhanet.conflict:<net>:<tool>` | `error` | A tool name is quarantined for a contract conflict, naming the differing host ([SAJHA Net](SAJHA%20Net.md#87-one-name-one-contract)); no ttl | The hosts agree again |
| SAJHA Net | `sajhanet.reactivated:<net>:<tool>` | `info` | A quarantined name is active again; ttl 60 minutes | The ttl passes |
| SAJHA Net | `sajhanet.catalog:<net>:<peer>` | `warning` | A peer's catalog was flagged (a cap exceeded, a contract hash that does not match); ttl 60 minutes | The ttl passes |
| SAJHA Net | `sajhanet.name:<net>:<tool>` | `warning` | A tool of this server is not offered: its qualified name would exceed 128 characters, or its published name is invalid or shared ([SAJHA Net](SAJHA%20Net.md#56-vendors-and-external-servers)); no ttl | An administrator clears it after giving the tool a `rename` |
| SAJHA Net | `sajhanet.external_servers` | `warning` | Some external servers are not offered (an invalid entry, a prefix clash); no ttl | Every external server is offered |
| SAJHA Net | `sajhanet.sponsored:<net>:<instance>` | `warning` | A sponsored server could not be started; no ttl | An administrator clears it after fixing the entry |
| SAJHA Net | `sajhanet.keysync:<net>:<member>` | `warning` | Pulling a member's key records keeps failing | A sync succeeds |
| SAJHA Net | `sajhanet.blocked_by:<net>:<member>` | `info` | A member publishes blocks naming this server; no ttl | It publishes none |
| SAJHA Net | `sajhanet.plugin:<source>:<name>` | `error` | A third-party plug-in cannot be imported, registers nothing or fails its contract check; no ttl | It loads at a later start |

The alert channel's optional fields are in [Observability](Observability.md) section 5.

**Adding a source.** Call the module API; it never raises:

```python
from sajha import notices
notices.raise_notice('mysubsystem.condition:subject', severity='error', source='mysubsystem',
                     title='One line for an operator', detail='What, what it affects, what to do.',
                     link='/console/page', audience='admin',
                     ttl_minutes=None,       # None: notices.default_ttl_minutes; 0: never expires
                     holder=None)            # a worker id for a condition each worker judges itself
notices.clear_notice('mysubsystem.condition:subject')
```

A polled condition can use `sajha.notices.sources.reconcile(prefix, desired, holder)`, which
raises every desired notice and clears the open ones under the prefix that are no longer
desired. Add the source's row to the table above and a test to `tests/test_notices.py`.

## 5. API

Every route is in the [API Reference](../protocol/API%20Reference.md) (section 4.22).

| Route | Who | What |
|---|---|---|
| `GET /api/notices` | signed in | The caller's view: `{enabled, notices, banner, others, badge, is_admin}`; `?cleared=1` adds `cleared`; an administrator signed in by cookie also gets `csrf` for the actions |
| `GET /api/notices/stream` | signed in | The same view as server-sent events (`event: notices`), sent at once and after every change |
| `GET /api/admin/notices` | admin | Every notice: `?state=open` (default), `cleared` or `all`; `?source=` |
| `POST /api/admin/notices/{id}/acknowledge` | admin | Acknowledge an active notice (cookie callers send `X-CSRF-Token`) |
| `POST /api/admin/notices/{id}/clear` | admin | Clear it now (reason `admin`) |

## 6. Configuration

Every `notices.*` key, its default and how it is read: [Configuration
Reference](../getting-started/Configuration%20Reference.md#system-notices). Forwarding to alert
channels, for example:

```yaml
notices:
  forward:
    - { min_severity: critical, channel: { type: webhook, url: "https://hooks.example.com/sajha" } }
    - { min_severity: error, channel: { type: email, to: ["ops@example.com"] } }
```

A forwarded message is `{type: "sajha.notice", transition, notice, at}`; it is sent when a notice
is raised or escalated, by the worker that made the transition. Webhooks go through the same
allow-list and SSRF guard as alert webhooks (`observability.alerts_webhook.*`); email through
`observability.alerts_email`.

## 7. Tests

`tests/test_notices.py`: raising, refreshing and clearing, one entry per id, ttl clearing,
escalation, worker holders, the `max_active` bound, switching off; acknowledgement by an
administrator, refusal for other users and without the CSRF token, `critical` staying on the
banner; audience (`admin` notices invisible to other users, `everyone` shown to all); two
services on one database state store seeing and changing the same notices; forwarding; each
source above; the API, the stream and the banner, badge and panel in rendered pages.
`scripts/check_mobile.py` (`--notices`) checks the banner, panel and badge at phone and desktop
widths in each theme.
