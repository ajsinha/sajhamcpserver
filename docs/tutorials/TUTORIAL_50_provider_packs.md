# Tutorial 50: Provider Packs

Connecting a service that users ask for (GitHub, Slack, Box) used to take two jobs: configure the
connected-account provider, then import the service's API in Studio and bind it to the users' accounts.
A **provider pack** does both in one reviewed step: a provider preset and an API Import of a bundled,
licensed excerpt of the vendor's OpenAPI spec, whose tools call the service as the person who asks. This
tutorial lists the bundled packs, plans the GitHub pack, installs it through the review-and-approve gate,
sees its tools ask an unlinked user to connect, and uninstalls it. Packs are owned by
[Connected Accounts §11](../architecture/Connected%20Accounts.md#11-provider-packs); connected accounts
in general by the rest of that guide, and the import by [API Import](../architecture/API%20Import.md).

**What was verified.** Every step below was run as written from a checkout, with a scratch SQLite
database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`) and directory for loaded results
(`SAJHA_BI_SCRATCH_DIR`), and the default offline mock LLM provider. The outputs are from that run. Linking
a real GitHub account needs an OAuth app registered with GitHub and a browser, which this run did not
have: the client id below is a placeholder, so the tutorial stops at the point where a user would link,
and step 6 says what you need for that. Installing writes into `config/` (the preset, the import, the tool
configurations and the install record); step 7 removes it all again.

## What you'll learn

- What a pack bundles, and how to read one before installing it
- How the plan shows everything an install would do, and why its hash matters
- How an install is refused without approval, or when anything changed since the review
- What the installed tools do for a user who has not linked the service
- How to uninstall a pack

## Prerequisites

- A checkout with its virtual environment ([Quick Start](../getting-started/Quick%20Start.md)) and the
  development API key `sja_test_admin_dev_key_0001` from `config/apikeys.json` (role `admin`).
- For real use: an OAuth app registered with the service (for GitHub, Settings, Developer settings, OAuth
  Apps), its client id, and its client secret in an environment variable on the server.
- `call.py`, the one-tool MCP helper of [Tutorial 48](TUTORIAL_48_sandbox_egress.md).

## 1. The bundled packs

From a shell in the checkout, against its configuration:

```bash
.venv/bin/python -m sajha.packs list
.venv/bin/python -m sajha.packs show github | python3 -c "
import json,sys; d=json.load(sys.stdin); p=d['pack']
print(p['title'], p['version'], '| prefix', p['prefix'], '| base', p['base_url'])
for o in p['operations']: print('  ', o)
s=p['source']; print('source', s['url'], s['file'], s['revision'][:12], s['licence'])"
```

```text
box          1.0.0    not installed        Box (Apache-2.0)
github       1.0.0    not installed        GitHub (MIT)
slack        1.0.0    not installed        Slack (MIT)
GitHub 1.0.0 | prefix github | base https://api.github.com
   GET /user
   GET /user/repos
   GET /repos/{owner}/{repo}/issues
   POST /repos/{owner}/{repo}/issues
   GET /repos/{owner}/{repo}/pulls
   GET /search/issues
source https://github.com/github/rest-api-description descriptions/api.github.com/api.github.com.json 58b1e0c00b39 MIT
```

Each pack names where its spec came from, at which revision and under which licence (`show` also prints
the licence text), and records the spec's SHA-256: a spec that does not match is refused. The spec is in
the pack and is never fetched when you install.

## 2. Start the server

```bash
P=/tmp/t50; mkdir -p $P
export SAJHA_DB_PATH=$P/t50.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  GITHUB_CLIENT_SECRET=tutorial-not-a-real-secret
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195
```

The same steps work from the shell (`python -m sajha.packs plan | install | uninstall`); here they go
through the admin API, `/api/admin/packs`.

## 3. Plan: what an install would do

The administrator supplies what belongs to them: the OAuth client id, and the client secret as a
reference (`env:NAME`, `file:/path` or `db:...`), never the secret itself:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
plan() { curl -s -X POST http://127.0.0.1:3195/api/admin/packs/github/plan -H "$K" -H 'Content-Type: application/json' -d "$1"; }
plan '{}' | python3 -c "import json,sys; print(json.load(sys.stdin)['errors'])"
plan '{"client_id":"Iv1.tutorial","client_secret_ref":"abc123"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['error'])"
```

```text
['provider github has no client id: give client_id (the OAuth app you registered with GitHub), or configure accounts.providers.github']
client_secret_ref must be a reference such as env:NAME, file:/path or db:table/key, never the secret itself
```

With both:

```bash
plan '{"client_id":"Iv1.tutorial","client_secret_ref":"env:GITHUB_CLIENT_SECRET"}' | python3 -c "
import json,sys; p=json.load(sys.stdin)
print('errors', p['errors'], 'warnings', p['warnings'])
v=p['provider']; print('provider', v['id'], v['api_hosts'], v['scopes'], v['redirect_uri'])
print('folder', p['api']['folder'], 'binding', p['api']['binding'])
for o in p['api']['operations']: print(' ', o['key'], '->', o['name'], o['status'], 'readOnly' if o['annotations'].get('readOnlyHint') else 'write')
print('policy', p['policy']['deploy']['effect']); print('hash', p['hash'])"
```

```text
errors [] warnings []
provider github ['api.github.com', 'uploads.github.com'] ['read:user', 'repo'] http://localhost:3002/account/connections/github/callback
folder github_pack binding {'github': {'type': 'connected_account', 'provider': 'github', 'scopes': ['repo']}}
  GET /user -> github_users_get_authenticated new readOnly
  GET /user/repos -> github_repos_list_for_authenticated_user new readOnly
  GET /repos/{owner}/{repo}/issues -> github_issues_list_for_repo new readOnly
  POST /repos/{owner}/{repo}/issues -> github_issues_create new write
  GET /repos/{owner}/{repo}/pulls -> github_pulls_list new readOnly
  GET /search/issues -> github_search_issues_and_pull_requests new readOnly
policy allow
hash 583a0548a2a31464ead43662636c8c9e0f2e7b630235a1a10563b51f671499d7
```

The plan is everything the install would do: the provider as the registry would build it, the redirect
URI to register with GitHub (built from `accounts.public_url`, else `mcp.auth.public_url`, else the
address you asked for the plan on, exactly as the connect flow builds it; set one so it names your server), each operation as API Import would deploy it, and the policy engine's verdict on the
pseudo tool call `studio.deploy` with `{"tool": "pack:github", "kind": "pack"}`. A pack whose API is not
on its provider's `api_hosts` is an error here, because a user's token would go elsewhere. The **hash**
covers all of it.

## 4. Install

```bash
B='"client_id":"Iv1.tutorial","client_secret_ref":"env:GITHUB_CLIENT_SECRET"'
H=583a0548a2a31464ead43662636c8c9e0f2e7b630235a1a10563b51f671499d7
install() { curl -s -X POST http://127.0.0.1:3195/api/admin/packs/github/install -H "$K" -H 'Content-Type: application/json' -d "$1" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('success'), d.get('error') or d.get('message'))"; }
install '{'"$B"',"hash":"'$H'"}'
install '{"client_id":"Iv1.other","client_secret_ref":"env:GITHUB_CLIENT_SECRET","hash":"'$H'","approve":true}'
install '{'"$B"',"hash":"'$H'","approve":true}'
```

```text
False an install needs explicit approval (approve: true) after you have reviewed the plan
False the plan changed since you reviewed it (the pack, its inputs or the tools it would replace); review the current plan and install again
True Installed GitHub: provider github and 6 tool(s). Users link their account on Connected accounts; register http://localhost:3002/account/connections/github/callback with GitHub.
```

Another client id makes another plan, with another hash, so the reviewed hash no longer matches. With a
`require_approval` rule on `studio.deploy` the install would instead create an approval request for
another administrator. What the install wrote:

```text
config/accounts/provider_presets/github.json
config/api_imports/github.json
config/packs/github.json
config/tools/github_pack/github_issues_create.json
config/tools/github_pack/github_issues_list_for_repo.json
config/tools/github_pack/github_pulls_list.json
config/tools/github_pack/github_repos_list_for_authenticated_user.json
config/tools/github_pack/github_search_issues_and_pull_requests.json
config/tools/github_pack/github_users_get_authenticated.json
```

All through the storage backend, so on a cloud backend they go to the bucket, and every worker picks up
the new preset and tools within seconds. The install is audited (`config_change`, `packs.install`).

## 5. The provider and the tools

GitHub is now a provider users can link:

```bash
curl -s http://127.0.0.1:3195/api/accounts/connections -H "$K" | python3 -c "
import json,sys
for p in json.load(sys.stdin)['providers']: print(p['id'], p['title'], p['scopes'], 'configured', p['configured'])"
```

```text
github GitHub ['read:user', 'repo'] configured True
```

A tool called by someone who has not linked GitHub does not fail with a bare error; it says where to
connect:

```bash
.venv/bin/python call.py github_users_get_authenticated '{}' 2>/dev/null
```

```text
Connect your GitHub account at http://localhost:3002/account/connections?connect=github, then retry.
```

The API key here belongs to the development user `testadmin`, so "your" is that user's account.

## 6. Linking for real

With a real OAuth app (its client id in the install, its secret in the variable the reference names, and
the redirect URI from the plan registered with GitHub), each user opens **Connected accounts**
(`/account/connections`), chooses **Connect** for GitHub and signs in at GitHub. From then on the pack's
tools call GitHub with that user's token, which is sent only to the provider's `api_hosts`; another user's
calls use their own link or are asked to connect. `github_issues_create` is a write: the policy engine
treats it like any tool that does not declare `readOnlyHint`, so a rule can hold it for approval
([Policy and Audit](../architecture/Policy%20and%20Audit.md)).

## 7. Uninstall

```bash
curl -s -X POST http://127.0.0.1:3195/api/admin/packs/github/uninstall -H "$K" -H 'Content-Type: application/json' -d '{}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['message'], d['preset_removed'])"
```

```text
github: removed 6 tool(s) and the provider preset True
```

The tools, the import and the preset are gone, and a call to one of the tools now answers
`Tool not found`. Users' links stay in the vault until they or an administrator remove them.

## Summary

- A pack is a provider preset plus a reviewed API Import of a bundled, licensed spec excerpt; `python -m
  sajha.packs list | show` reads them
- `plan` shows the provider, the redirect URI, every tool and the policy verdict, and returns a hash
- `install` needs that hash and `approve: true`, and is refused when anything changed since the plan
- The installed tools act as the calling user and ask an unlinked user to connect; `uninstall` removes
  the tools and the preset

## Next

- The pack format, the bundled packs and their limits: [Connected Accounts §11](../architecture/Connected%20Accounts.md#11-provider-packs)
- [Tutorial 51: Personal RAG over Connected Accounts](TUTORIAL_51_personal_rag.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
