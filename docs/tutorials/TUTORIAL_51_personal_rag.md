# Tutorial 51: Personal RAG over Connected Accounts

Document search over SAJHA's own guides and an administrator's folders answers the same for everyone.
Personal RAG answers from **your** documents: files in a Google Drive folder, OneDrive, a SharePoint
library, a GitHub repository or a Confluence space, read with the account you linked on Connected
accounts, so what is indexed for you is exactly what you may read there, and nobody else's search
reaches it. This tutorial configures a GitHub source, looks at it before and after linking, and shows
the tool, the routes and what a sync reports. The design, every source kind and its fields, isolation,
incremental sync and OCR are in
[Intelligence Layer](../architecture/Intelligence%20Layer.md#documents-from-connected-accounts); linking
an account is [Connected Accounts](../architecture/Connected%20Accounts.md) and
[Tutorial 18](TUTORIAL_18_connect_your_accounts.md).

**What was verified.** Every step below was run as written against a server started from a checkout
on a scratch database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`), scratch directory
(`SAJHA_BI_SCRATCH_DIR`) and vector stores, with the default offline mock provider, and the outputs are
from that run. The run had no GitHub OAuth app, so it stops where a real link is needed: the
`Connect` redirect to GitHub is shown, and so is everything SAJHA reports while the source is not
linked. With a linked account, steps 6 and 7 return your passages instead.

## What you'll learn

- How `ai.rag.accounts.sources` names a source that each user's own account reads
- What `GET /api/ai/docs/mine` says about each source: linked, documents, last sync
- What `sajha_search_my_docs` returns, including the sources you have not linked yet
- How linking starts, and what the first sync and later syncs do
- Why another user's search, an API key or `sajha_search_docs` never sees your passages

## Prerequisites

- A SAJHA checkout and its environment ([Tutorial 1](TUTORIAL_01_getting_started.md)), signed in as a
  user (the examples use the development user `testadmin` / `testadmin-dev-1` from `config/users.json`).
- To index real documents: a GitHub OAuth app and the `github` provider enabled with its client id and
  secret reference ([Tutorial 18](TUTORIAL_18_connect_your_accounts.md), steps 1 and 2). The examples
  use a placeholder client id, which is enough for everything up to the GitHub sign-in page. A Google,
  Microsoft or Atlassian source needs that provider instead.

## 1. Configure a source

Sources live under `ai.rag.accounts` in `config/application.yml`; as one environment variable the whole
map is JSON in `SAJHA_AI_RAG_ACCOUNTS`. One GitHub source: the Markdown files under `docs/` of one
repository, on its default branch.

```yaml
ai:
  rag:
    accounts:
      sources:
        - name: team_notes
          kind: github
          repo: your-org/team-notes
          path: docs
          pattern: "*.md"
          title: Team notes on GitHub
```

Start the server with that, the GitHub provider, and `accounts.public_url` (the address in the links
SAJHA writes when no request is at hand, such as a background sync's "connect your account" message):

```bash
P=/tmp/t51; mkdir -p $P
export SAJHA_DB_PATH=$P/t51.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  SAJHA_AI_RAG_STORES_SQLITE_VEC_PATH=$P/rag/vectors.db SAJHA_AI_RAG_INDEX_SAJHA_DOCS=false \
  SAJHA_AI_RAG_ACCOUNTS='{"sources": [{"name": "team_notes", "kind": "github", "repo": "your-org/team-notes", "path": "docs", "pattern": "*.md", "title": "Team notes on GitHub"}], "path": "/tmp/t51/rag/personal.db"}' \
  SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_ID=Iv1.example \
  SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_SECRET_REF=env:GITHUB_OAUTH_CLIENT_SECRET \
  GITHUB_OAUTH_CLIENT_SECRET=not-a-real-secret \
  SAJHA_ACCOUNTS_PUBLIC_URL=http://127.0.0.1:3197
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3197
```

The personal passages go to their own store (`path` here; `ai.rag.accounts.store`), never the shared
index's, so `sajha_search_docs` cannot return them. A bad source entry leaves the personal index off
and is logged; with no sources, it and its tool are off.

## 2. Sign in and look at your sources

The personal routes answer for the signed-in user. Sign in with a cookie jar (the browser's way, used
again in step 5) and also take a SAJHA JWT for the calls that change something: with the cookie, a
`POST` would also need the console's CSRF token; a bearer token needs none. API keys get nothing from
personal sources, not even a key bound to your user.

```bash
J=$P/jar; B=http://127.0.0.1:3197
curl -s -c $J -b $J -o /dev/null -w "%{http_code}\n" -X POST $B/login -d user_id=testadmin -d password=testadmin-dev-1
T=$(curl -s -X POST $B/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id":"testadmin","password":"testadmin-dev-1"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s -b $J $B/api/ai/docs/mine | python3 -m json.tool
```

```text
302
{
    "enabled": true,
    "store": "sqlite_vec",
    "ocr": {
        "enabled": false,
        "engine": null,
        "installed": false,
        "hint": "OCR needs an optional dependency that is not installed: pip install rapidocr-onnxruntime, or pip install pytesseract and put the tesseract program on the PATH"
    },
    "sources": [
        {
            "name": "team_notes",
            "title": "Team notes on GitHub",
            "kind": "github",
            "provider": "github",
            "linked": false,
            "documents": 0,
            "syncing": false,
            "last_sync_at": null,
            "last_sync": null
        }
    ]
}
```

`linked: false`: this user has not linked GitHub, so nothing can be read as them. The `ocr` block says
whether scanned PDFs and images could be read (`ai.rag.ocr`, and an engine installed).

## 3. Search and sync before linking

```bash
curl -s -H "Authorization: Bearer $T" -X POST $B/api/ai/docs/mine/search -H 'Content-Type: application/json' -d '{"query": "release checklist"}'; echo
curl -s -H "Authorization: Bearer $T" -X POST $B/api/ai/docs/mine/sync -H 'Content-Type: application/json' -d '{}'; echo
sleep 1; curl -s -b $J $B/api/ai/docs/mine | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['sources'][0]['last_sync'], indent=1))"
```

```text
{"query":"release checklist","results":[],"count":0,"syncing":[]}
{"syncing":["team_notes"]}
{
 "status": "needs_connection",
 "documents": 0,
 "indexed": 0,
 "unchanged": 0,
 "removed": 0,
 "skipped": 0,
 "chunks": 0,
 "errors": [],
 "truncated": false,
 "reason": "not_connected",
 "error": "Connect your GitHub account at http://127.0.0.1:3197/account/connections?connect=github, then retry."
}
```

The sync runs in the background and records why it could not read anything; the link in its message
is built from `accounts.public_url`.

## 4. The tool: `sajha_search_my_docs`

The same search for MCP clients, LLM tools and Ask SAJHA is the tool `sajha_search_my_docs`, listed
only while sources are configured. It also names the sources you have not linked and where to link
them. Here it is called as `testadmin` with the JWT (the test admin key would be refused: keys have no
connected accounts):

```bash
curl -s -X POST $B/api/tools/execute -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"tool": "sajha_search_my_docs", "arguments": {"query": "release checklist"}}'; echo
```

```text
{"success":true,"result":{"query":"release checklist","results":[],"count":0,"syncing":[],"not_linked":[{"source":"team_notes","provider":"github","connect":"/account/connections?connect=github"}]}}
```

Its arguments are `query`, `top_k` (1 to 20) and `source` (one source by name). A result, once there
are passages, carries `citation`, `source`, `document`, `title`, `section`, `url`, `score` and the
passage text.

## 5. Link GitHub

**Account > Connected accounts** (`/account/connections`) has a **Connect** button per provider; the
`connect` link in step 4 opens the page with GitHub selected. The button posts the page's form, and
SAJHA redirects the browser to GitHub's consent page with PKCE:

```bash
CSRF=$(curl -s -c $J -b $J $B/account/connections | grep -o 'name="csrf" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//')
curl -s -c $J -b $J -o /dev/null -D - -X POST $B/account/connections/github/connect -d csrf=$CSRF \
  | grep -i -E "^HTTP|^location" | sed 's/state=[^&]*/state=.../; s/code_challenge=[^&]*/code_challenge=.../'
```

```text
HTTP/1.1 303 See Other
location: https://github.com/login/oauth/authorize?response_type=code&client_id=Iv1.example&redirect_uri=http%3A%2F%2F127.0.0.1%3A3197%2Faccount%2Fconnections%2Fgithub%2Fcallback&state=...&scope=read%3Auser+repo&code_challenge=...&code_challenge_method=S256
```

With a real OAuth app you approve on GitHub, GitHub sends you back to the callback, and the token is
stored encrypted in the vault ([Tutorial 18](TUTORIAL_18_connect_your_accounts.md) step 3). This run
stops here: `Iv1.example` is not an app GitHub knows.

## 6. The first sync and the ones after it

Once linked, `GET /api/ai/docs/mine` shows `linked: true`. The next search finds the source never
synced, starts a background sync and says so in `syncing`; a moment later the same search returns
your passages. What a sync does:

- It lists the files under `path` that match `pattern`, with **your** token, sent only to the
  provider's `api_hosts` (for GitHub, `api.github.com` and `uploads.github.com`).
- Each file's change token (for GitHub, the blob sha) is kept with its passages. A later sync downloads
  only files whose token changed, removes files that are gone, and, for GitHub, skips the listing
  entirely when the branch's commit has not moved.
- A search starts a new background sync when the source is older than
  `ai.rag.accounts.stale_after_seconds`; `ai.rag.accounts.sync_interval_seconds` sweeps every linked
  user on a timer (off by default). `POST /api/ai/docs/mine/sync` syncs now.
- A 401 refreshes the token once, then marks the link for reconnection.

`last_sync` reports `status`, `documents`, `indexed`, `unchanged`, `removed`, `skipped`, `chunks` and
any `errors`, as in step 3.

## 7. Who sees what

- **Only you.** Each passage's source is `acct:<owner>:<source>`, where `<owner>` is a hash of your user
  id, and every search is filtered by the caller's own keys and checked again per hit. A document two
  users can both read is indexed once for each of them.
- **Only while linked.** A search covers only sources whose link is active now. Disconnect GitHub, or
  lose access to the repository (GitHub answers 403 or 404), and the next sync removes your passages
  from that source.
- **Not the shared index.** `sajha_search_docs` searches SAJHA's guides and the administrator's
  sources; the personal store is separate:

```bash
curl -s -X POST $B/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "sajha_search_docs", "arguments": {"query": "release checklist"}}'; echo
```

```text
{"success":true,"result":{"query":"release checklist","results":[],"count":0}}
```

## Summary

- `ai.rag.accounts.sources` names sources; each user's own linked account reads them, into a store of
  its own
- `GET /api/ai/docs/mine` shows each source's link and last sync; `POST .../sync` and `POST .../search`
  sync and search for the signed-in user
- `sajha_search_my_docs` searches your passages and lists the sources you have not linked
- Syncs are incremental by change token; a lost link or lost access removes your passages

## Next

- The design and every source kind: [Intelligence Layer](../architecture/Intelligence%20Layer.md#documents-from-connected-accounts)
- [Tutorial 52: Planner Routing Learned from Results](TUTORIAL_52_planner_routing_learning.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
