# GitHub Integration

**Status: works per user with personal access tokens (`token_user`, phase 7.2); OAuth sign-in
(`oauth_user`) comes in phase 7.3.** How SAJHA reaches GitHub (repositories, issues, pull requests,
code search, Actions, Projects). Acting as each user rests on
[Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md). How proxied servers work today is in [Federation](Federation.md).

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

## 3. What works today

- **Each user with their own personal access token** (`token_user`): copy
  `config/mcp_servers/11_github_token_user.json.example` into `config/mcp_servers.json`. Each user saves a
  GitHub personal access token once on **Server connections** (`/account/server-connections/github`; the
  page links to GitHub's token page and checks the token's shape, then tests it with `tools/list`). Calls
  then carry that user's token, so GitHub's own permissions and attribution apply; a user without a token
  is asked to connect; a token GitHub refuses marks the connection "needs re-connect". Discovery uses the
  first connected user's token unless the entry names a discovery token. Configuration and behaviour:
  [Federation §3, Per-user credentials](Federation.md#per-user-credentials-token_user).
- **One shared token** (a static `Authorization: Bearer ${GITHUB_PAT}` header,
  `config/mcp_servers/04_remote_bearer_token.json.example`) still works. Its limit: **every SAJHA user acts
  as the token's owner**. Use it only with a read-only, narrowly scoped token for a shared purpose (for
  example public issue search).
- **Not yet:** OAuth sign-in (phase 7.3), so Enterprise Managed Users whose enterprise disables personal
  access tokens cannot connect yet.

## 4. With per-user sign-in

- Each user connects GitHub once (a personal token under `token_user` now, OAuth in phase 7.3); calls
  carry their own identity, so repository permissions and audit attribution are GitHub's own.
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
