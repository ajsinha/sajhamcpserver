# System Notices

> **Status: design, not built.** Planned for wave 1 of the
> [Implementation Plan](Implementation%20Plan.md); later waves add their own sources.

A **system notice** is SAJHA telling the people who run it that something needs attention: a
tool was quarantined, a peer in a SAJHA Net is unreachable, the database schema is out of date,
the memory guard is refusing work, a certificate is about to expire. Today such conditions are
written to the log, counted in metrics or sent by alert rules ([Observability](Observability.md)
section 5), but nothing in the console shows them to an operator who is looking at it. Notices
are that missing piece: one service every subsystem reports into, and one place in the console
that shows what is wrong right now.

---

## 1. What a notice is

| Field | Meaning |
|---|---|
| `id` | Stable identity of the condition, chosen by the source (for example `sajhanet.contract_conflict:risk-net:var_calc`). Raising the same id again updates the notice instead of adding a second one. |
| `severity` | `info`, `warning`, `error` or `critical` |
| `source` | The subsystem that raised it (`sajhanet`, `llm_tools`, `db`, `federation`, `alerts`, ...) |
| `title` | One line, written for an operator ("Tool `var_calc` quarantined in risk-net") |
| `detail` | What happened, what it affects, and what to do, in a few sentences |
| `link` | The console page that shows or fixes it |
| `since`, `last_seen` | When the condition started and was last confirmed |
| `audience` | `admin` (default) or `everyone` for conditions every signed-in user should know about (for example a remote instance being down that hosts tools they use) |
| `state` | `active`, `acknowledged` or `cleared` |
| `acknowledged_by`, `acknowledged_at` | Who acknowledged it, if anyone |

## 2. Lifecycle

- **Raised** by a source when its condition starts, with a stable id.
- **Refreshed** while the condition holds (`last_seen` moves; severity may change).
- **Cleared automatically** when the source reports the condition has ended, or when it has not
  been refreshed for its `ttl` (a source that dies cannot leave a stale notice forever).
- **Acknowledged** by an administrator: the banner stops shouting, the notice stays on the
  status panel until it clears. Acknowledgement never hides a `critical` notice from the banner.
- **Every transition is an audit event**, so the history of what went wrong and who saw it is
  kept under the audit log's retention.

Notices live in the state store, so every worker of an instance sees the same set, and are
bounded: at most `notices.max_active` active notices (oldest `info` first to go) and one entry
per id.

## 3. Where they appear

| Place | Shows |
|---|---|
| **Banner** on every console page | The most severe active, unacknowledged `error` or `critical` notice for the viewer's audience, with a count of the others and a link to the status panel |
| **System status panel** on the dashboard | Every active notice, grouped by severity, with source, since, detail, link, and an acknowledge action for administrators; a toggle to show recently cleared ones |
| **Navbar badge** | The number of active notices at `warning` or above for the viewer |
| **API** | Admin endpoints to list, acknowledge and clear notices, for scripts and other consoles |
| **Alert channels** | A notice of a chosen severity can also be sent through an alert channel (log, webhook, email); and an alert rule can raise a notice through a new `notice` channel, so existing rules appear in the console too |

The banner and panel follow the console's conventions: severity in words and colour (never colour
alone), all four themes, phone-width layouts, and updates by server-sent events so a notice appears
without a page reload.

## 4. Sources

Each source owns the ids it raises and is responsible for clearing them.

| Source | Notices | Wave |
|---|---|---|
| Database | schema check found missing tables or columns (with the SQL to run); upgrade helper findings | 1 |
| Resilience | circuit breakers open for tools, providers or upstreams | 1 |
| Workflows | scheduled runs failing repeatedly | 1 |
| Intelligence layer | a model alias with no available candidate; a provider failing | 1 |
| Alert rules | any rule using the `notice` channel | 1 |
| Federation | an upstream down; tools held for approval | 1 |
| LLM tools | the memory guard at its soft or hard limit; runs refused as `busy`; spool full | 2 |
| SAJHA Net | a tool quarantined by a contract conflict; an instance-name conflict (its own or one it saw); a member suspect, dead or left (an error when it hosts tools this instance uses); seeds unreachable or the net not joined; a certificate expiring or expired; the revocation list stale; key-directory sync failing; the CA instance unreachable for renewal; a block added against this instance. Details in [SAJHA Net](SAJHA%20Net.md) | 4 |

## 5. Configuration

```yaml
notices:
  enabled: true
  max_active: 500
  default_ttl_minutes: 30        # a notice not refreshed for this long is cleared
  banner_min_severity: error     # error | critical
  forward:                       # optionally also send notices through alert channels
    - { min_severity: critical, channel: { type: webhook, url: "https://hooks.example.com/sajha" } }
```

## 6. Tests

- A source raising, refreshing and clearing a notice; the same id never duplicated; ttl clearing.
- Acknowledgement by an administrator; non-administrators cannot acknowledge; `critical` stays on
  the banner.
- Audience: `admin` notices invisible to other users; `everyone` notices shown to all.
- Several workers see the same notices (state store backends).
- Banner, panel and badge in all four themes at phone and desktop widths; live update without
  reload.
- Each wave adds tests for the notices its sources raise.
