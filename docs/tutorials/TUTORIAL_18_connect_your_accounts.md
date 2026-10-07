# Tutorial 18: Connect Your Accounts

Link your GitHub account to SAJHA once, then let a tool, an MCP client and Ask SAJHA act as
you on GitHub. You will register a GitHub OAuth app, enable the `github` provider, link the
account, call `github_list_my_repos` three ways, and disconnect.

Design and every option: [Connected Accounts](../architecture/Connected%20Accounts.md).

## Prerequisites

- SAJHA running locally on port 3002 ([Quick Start](../getting-started/Quick%20Start.md)),
  with an admin sign-in ([Tutorial 1](TUTORIAL_01_getting_started.md))
- A GitHub account

## 1. Register a GitHub OAuth app

On GitHub: **Settings → Developer settings → OAuth Apps → New OAuth App**.

| Field | Value |
|---|---|
| Application name | SAJHA (local) |
| Homepage URL | `http://localhost:3002` |
| Authorization callback URL | `http://localhost:3002/account/connections/github/callback` |

Register it, then **Generate a new client secret**. Note the client ID and the secret.

The callback URL must match what SAJHA sends exactly. SAJHA builds it from
`accounts.public_url` (or `mcp.auth.public_url`); when both are empty it uses the address
you browse SAJHA on, so open SAJHA at `http://localhost:3002`, not `127.0.0.1`.

## 2. Enable the provider

The secret never goes into `config/application.yml`; the config names an environment
variable instead:

```bash
export SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_ID=Ov23li...           # the client ID
export SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_SECRET_REF=env:GITHUB_OAUTH_CLIENT_SECRET
export GITHUB_OAUTH_CLIENT_SECRET=...                                # the client secret
export SAJHA_ACCOUNTS_PUBLIC_URL=http://localhost:3002
python run_server.py
```

(The same in YAML: `accounts.providers.github.client_id` and `client_secret_ref` under
`accounts:` in `config/application.yml`.)

Sign in as an administrator and open **Admin → Connected accounts**
(`/admin/connections`): the Providers table shows `github` as **enabled**. The GitHub tools
now appear on the Tools page: `github_list_my_repos`, `github_create_issue`,
`connected_http_request`.

## 3. Link your account

Open the user menu (your name, top right) → **Connected accounts**
(`/account/connections`). The GitHub card says **Not linked**. Click **Connect GitHub**.

GitHub asks you to authorize *SAJHA (local)* for `read:user` and `repo`. Approve. You are
back on the page and the card says **Linked**, with your GitHub login, the scopes granted
and "does not expire" (GitHub OAuth-app tokens do not; Google and Microsoft tokens expire
and SAJHA renews them).

What happened: SAJHA created a one-time `state`, a PKCE verifier and a browser cookie,
GitHub returned a code to the callback, and SAJHA exchanged it for a token, which it stored
encrypted. The administrator page now lists your link, without the token.

## 4. Call the tool from the console

**Tools → All tools → github_list_my_repos → Execute** with `{"limit": 5}`. The result
lists your repositories, private ones included, with `"account"` set to your GitHub login.

From the REST API, sign in for a JWT (an API key will not do: API keys belong to no user, so
they have no connected accounts):

```bash
TOKEN=$(curl -s -X POST localhost:3002/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id":"admin","password":"<your password>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -X POST localhost:3002/api/tools/execute -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"tool":"github_list_my_repos","arguments":{"limit":3}}'
```

## 5. See what a client without a link gets

Disconnect (step 7) and call the tool again with `curl`: the answer is HTTP **428** with
`"error_code": "connected_account_required"` and a `connect_url` pointing at
`/account/connections?connect=github`.

An MCP client that declared URL-mode elicitation gets the same URL as an elicitation: on MCP
2026-07-28 an `InputRequiredResult` (key `sajha.connect.github`), on 2025-11-25 the error
`-32042`. It opens the page, you link, and it retries the call. A client without that
capability gets a tool error naming the URL.

## 6. Ask SAJHA

With the account disconnected, open **AI → Ask SAJHA** and ask *"List my GitHub
repositories"*. SAJHA picks `github_list_my_repos`, finds no link and shows a **Connect
GitHub** card. Click it (a new tab), approve on GitHub, come back and click **I have
connected it: ask again**. The answer lists your repositories.

`github_create_issue` is marked destructive: Ask SAJHA asks you to confirm before it opens
an issue as you.

## 7. Disconnect

On `/account/connections`, **Disconnect** on the GitHub card. SAJHA asks GitHub to revoke
the grant (the OAuth app's grant endpoint) and deletes the token. An administrator can do
the same for any user on `/admin/connections` (for example when someone leaves).

## What next

* Other services: `slack`, `google`, `microsoft`, `atlassian` and `notion` are templates
  too; each needs an app registered with that service and its callback URL
  `<origin>/account/connections/<id>/callback`.
* Bind more of GitHub's API: copy `connected_http_request.json` and change its paths
  ([Connected Account Tools Reference Guide](../tools/enterprise/Connected%20Account%20Tools%20Reference%20Guide.md)).
* Put an MCP server that takes GitHub tokens behind SAJHA with
  `auth: {type: connected_account, provider: github}`: each user's calls carry their own
  token ([Connected Accounts §7](../architecture/Connected%20Accounts.md#7-federation-token-passthrough)).
* Next tutorial: [Import an OpenAPI Spec](TUTORIAL_19_import_an_openapi_spec.md)
