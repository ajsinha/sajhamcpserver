# Google Integration

**Status: configurable, not verified against Google's live servers.** Per-user OAuth sign-in to proxied
MCP servers (`oauth_user`) is built, and `config/mcp_servers/15_google_workspace_oauth.json.example`
configures a Google Workspace server with an OAuth client in your Google Cloud project; it is tested
against a fake OAuth-protected server, not against Google. How SAJHA should reach Gmail, Google Drive,
Google Calendar and the other Google Workspace services, and which other public MCP servers are worth
the same treatment; how proxied servers work is in [Federation](Federation.md).

## 1. Recommendation

Proxy Google's own MCP servers rather than writing Google tools by hand.

1. Per-user OAuth for proxied MCP servers: built (`oauth_user`,
   [Per-user OAuth sign-in](Federation.md#per-user-oauth-sign-in-oauth_user)).
2. Add Google's Drive and Calendar MCP servers as external proxied servers (`vendor: google`), read
   tools first.
3. Add the Gmail server once the approval rules in section 5 are agreed.
4. Writes (send, share, create events) always behind an approval rule in SAJHA's policy engine: the
   shipped rule for proxied writes covers every tool without `readOnlyHint` ([Policy and Audit §5.1](Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes)).

The same per-user sign-in also lets SAJHA proxy every other hosted MCP server that asks each user to
sign in (section 7), which hand-written Google tools would not.

## 2. What exists today

- **Connected accounts** ([Connected Accounts](Connected%20Accounts.md)): a user links Google Workspace
  once (OAuth with PKCE, tokens in the encrypted vault), and a few SAJHA tools act as that user.
- **Google tools in SAJHA:** a `google` folder with web search, and a Drive search tool in the
  `connected_accounts` folder (the live list is the Tools page, `google` domain).
- **Proxied MCP servers** ([Federation](Federation.md)): an external server's tools are offered as
  `<vendor>__<tool>` under SAJHA's governance. With `auth.type: oauth_user` each user signs in at the
  vendor once on Server connections and the server's tools then act as that user.

## 3. Google's MCP servers

Google documents remote MCP servers for Workspace, one per product (for example Gmail, Drive and
Calendar endpoints under `googleapis.com`), configured in a Google Cloud project with OAuth
credentials ([Google's guide](https://developers.google.com/workspace/guides/configure-mcp-servers)).
Google's May 2026 announcement describes Gmail (profile, search, drafting, read and write), Drive
(fetching, listing, uploading, permissions) and Calendar (free times, managing events)
([Workspace Updates](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html)).
Sources disagree on general availability (some still describe a gated developer preview); Google's
guide is the authority. Check the current endpoints, quotas and availability there before building.

## 4. Why proxy, and what SAJHA adds

| | Proxy Google's servers | Write Google tools in SAJHA |
|---|---|---|
| Who maintains the tools | Google | SAJHA (about twenty tools, each to keep working as Google's APIs change) |
| Tool quality and shape | Google's choice | SAJHA's choice |
| Per-user sign-in | `oauth_user` (built) | Uses connected accounts |
| Reuse | `oauth_user` also serves every hosted MCP server that needs sign-in | Google only |

Either way SAJHA adds what Google's servers do not: per-user identity carried end to end, role and
key access rules, approvals before anything is sent or shared, the audit trail, residency rules (so
mail content cannot travel to another SAJHA Net member), and sharing the tools across a SAJHA Net.

## 5. Risks and rules

- **Prompt injection.** An email or document is untrusted text. An assistant that reads mail and can
  also send it is the classic attack path. Every write tool (send, reply, share, upload, create or
  change an event) requires a human approval under the shipped rule for proxied writes
  ([Policy and Audit §5.1](Policy%20and%20Audit.md#51-the-shipped-rule-for-proxied-writes)), as long as it is enabled; mail and document content is screened
  and treated as untrusted by the planners; see the [Adversarial QA Plan](Adversarial%20QA%20Plan.md).
- **Google's app review.** Gmail's restricted scopes need Google's verification and a security
  assessment for apps used by personal accounts. An **Internal** OAuth app on the organisation's own
  Workspace avoids that review; it is the practical route for an intranet deployment.
- **Least privilege.** Read-only scopes by default; write scopes granted per user only when needed.
- **Residency.** Classify Gmail and Drive results so they never leave the server that fetched them
  unless a rule allows it.
- **Testing.** Automated tests run against a fake Google MCP server; a live check needs the
  operator's Google Cloud project and a test account.

## 6. How to configure it now

The design is [Per-User Sign-In for Proxied Servers](Per-User%20Sign-In%20for%20Proxied%20Servers.md);
configuration is [Per-user OAuth sign-in](Federation.md#per-user-oauth-sign-in-oauth_user).

1. **A Google Cloud project** (required): create an OAuth client of type "Web application", add
   `<accounts.public_url>/account/server-connections/oauth/callback` as an authorised redirect URI,
   enable the APIs of the servers you use, and configure the consent screen (an **Internal** app on your
   own Workspace avoids Google's verification). Set `GOOGLE_OAUTH_CLIENT_ID` and
   `GOOGLE_OAUTH_CLIENT_SECRET` in SAJHA's environment.
2. **The entry:** copy `config/mcp_servers/15_google_workspace_oauth.json.example`, put the server
   endpoint from Google's guide (section 3) in `url`, one entry per product, and remove
   `"enabled": false`. The template gives Google's documented OAuth endpoints and scopes
   ([web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server),
   [scopes](https://developers.google.com/identity/protocols/oauth2/scopes)): Drive and Calendar
   read-only for everyone, `drive.file` and `calendar.events` only for users who tick "allow changes",
   `access_type=offline` so Google returns a refresh token, and Google's own revocation endpoint.
3. **Each user** clicks "Connect with Google" on Server connections; calls then carry that user's token,
   refreshed before it expires; disconnecting revokes it at Google.
4. **Gmail:** `gmail.readonly` for reading; `gmail.send` only in `write_scopes` and only together with a
   policy rule that requires approval for sending (section 5). Gmail scopes are restricted: an external
   app needs Google's verification.

## 7. Other public MCP servers worth proxying

Vendors increasingly run their own hosted MCP servers. Most ask each user to sign in, which
`oauth_user` now handles (`config/mcp_servers/06_remote_oauth_sign_in.json.example` lists several); a
few work with a static key. The list below comes from public directories and vendor
announcements as of October 2026 and must be checked against each vendor's own documentation before
use.

| Area | Servers | Fit for SAJHA |
|---|---|---|
| Engineering | GitHub ([GitHub Integration](GitHub%20Integration.md)), Linear, Sentry, Atlassian ([Atlassian Integration](Atlassian%20Integration.md)), Cloudflare, Vercel, Neon | High: issues, code, incidents next to SAJHA's own tools |
| Knowledge and work | Notion, Asana, HubSpot, Slack | High: the same per-user pattern as Google |
| Payments | Stripe | Medium: read reports; writes behind approval |
| Market data | Alpha Vantage (official remote server), EODHD | High for the finance domain; SAJHA already has native Alpha Vantage tools, so compare before switching |
| Developer docs | Context7, DeepWiki | Works today without credentials (templates exist in `config/mcp_servers/`) |

Not found as official remote MCP servers in this review: Microsoft 365 (Outlook, Teams), Bloomberg,
LSEG, FactSet (FactSet was named as an enterprise partner, without a published MCP server), Polygon
(reported as community-built). Revisit these periodically.

Sources for this section: [VoltAgent's directory of official MCP servers](https://github.com/VoltAgent/official-mcp-servers),
[DataCamp: top remote MCP servers](https://www.datacamp.com/blog/top-remote-mcp-servers),
[OpenHelm: best remote MCP servers 2026](https://www.openhelm.ai/blog/best-remote-mcp-servers-2026),
[mcpservers.org remote servers](https://mcpservers.org/remote-mcp-servers),
[EODHD MCP server](https://eodhd.com/financial-apis/mcp-server-for-financial-data-by-eodhd),
[Top MCP servers for financial data](https://medium.com/data-science-collective/top-10-mcp-servers-for-financial-data-in-2026-3927fa3d4636).

## 8. Order of work

1. Per-user OAuth for proxied servers, with tests against a fake OAuth-protected MCP server: done.
2. Google Drive and Calendar servers as `config/mcp_servers.json` entries, read tools (the template
   exists); a live check against Google with the operator's Cloud project and a test account.
3. Gmail, after the approval policy for writes is agreed.
4. Templates for the section 7 servers that fit, each with its scope and approval notes.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
