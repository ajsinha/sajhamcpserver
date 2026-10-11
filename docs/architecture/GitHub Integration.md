# GitHub Integration

**Status: proposal, not built.** How SAJHA should reach GitHub (repositories, issues, pull requests,
code search, Actions, Projects). It depends on
[Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md) for anything
beyond a shared identity. How proxied servers work today is in [Federation](Federation.md).

## 1. Recommendation

Proxy GitHub's official MCP server as an external server (`vendor: github`, tools as
`github__<tool>`), with each user signed in as themselves once per-user sign-in exists. Do not write
GitHub tools by hand.

## 2. What GitHub offers

- **The remote server** at `api.githubcopilot.com/mcp/`, maintained by GitHub. It uses OAuth by
  default and also accepts a personal access token; with OAuth the user's approved scopes cap what it
  can do, with a token the token's scopes do (subject to organisation restrictions). For Enterprise
  Managed Users, personal access tokens are off unless an enterprise administrator enables them
  ([GitHub's setup guide](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/set-up-the-github-mcp-server)).
- **Toolsets** (repositories, issues, pull requests, Actions, Projects, code security and others) can
  be narrowed per connection, and the server hides tools a classic token's scopes do not allow
  ([GitHub changelog, January 2026](https://github.blog/changelog/2026-01-28-github-mcp-server-new-projects-tools-oauth-scope-filtering-and-new-features/)).
- **The open-source server** (`github/github-mcp-server`) can run locally over stdio — the route for
  GitHub Enterprise Server, proxied by SAJHA as an internal server.

Check the current endpoint, toolsets and authentication options in GitHub's documentation before
configuring.

## 3. What works today, and its limit

A `config/mcp_servers.json` entry with a static `Authorization: Bearer ${GITHUB_PAT}` header works now
(see `config/mcp_servers/04_remote_bearer_token.json.example`). Its limit: **every SAJHA user acts as
the token's owner** — they see that person's repositories and every write is attributed to them. Use
it only with a read-only, narrowly scoped token for a shared purpose (for example public issue search).

## 4. With per-user sign-in

- Each user connects GitHub once (OAuth, or a personal token under `token_user`); calls carry their own
  identity, so repository permissions and audit attribution are GitHub's own.
- Narrow toolsets per deployment (for example issues, pull requests and repositories; Actions read).
- Writes — creating issues or comments, opening or merging pull requests, dispatching workflows — go
  through SAJHA's approval policy.

## 5. Uses with the rest of SAJHA

- Ask SAJHA across sources: "which open issues mention the CVA limit, and what did last night's risk
  run report?" (GitHub tools with qlrisk and the data tools).
- Workflows: open an issue (with approval) when a scheduled check fails; post a summary comment.
- SAJHA Net: one server proxies GitHub for the organisation; other members use it with each caller's
  own connection at that server.

## 6. Risks

- Repository content, issues and comments are untrusted text: prompt injection can try to make an
  assistant open, merge or comment. Approvals on every write; screening of fetched text.
- Scope creep: start with read toolsets; grant write scopes per user and per need.
- Secrets in repositories must never flow into answers shared beyond the user: residency rules and
  the existing redaction apply to GitHub results like any other.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
