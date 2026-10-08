# Tutorial 30: Credential Files and Test Keys

Every forwarded SAJHA Net call carries exactly one API key, and the host decides what the call may do
from that key. This tutorial looks at where keys and users live (the database and three credential
files), what the test admin key and account do and why the lab uses them, how calls behave once the
test admin key is off and each caller's own key travels, and how a per-member key makes calls to one
member carry a key of your choosing. It runs on the [local test lab](TUTORIAL_29_local_test_lab.md).
The rules are in the [Security Model](../security/Security%20Model.md) ("Credential storage and files",
"Test admin key", "Keys toward particular members").

## What you'll learn

- What `config/users.json`, `config/apikeys.json` and `config/apikeys_db.json` hold, and which wins
- What a record marked `test_admin` does on one instance and across a net
- Which key a forwarded call carries, in which order, and how to see it in the host's audit
- How to turn the test admin key off and call across the net as yourself
- How to configure a per-member key

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), freshly reset
  (`lab.sh reset`, then `start`)

## Steps

### 1. The credential files

Users and API keys live in the database. Three files sit beside it, all git-ignored and owner-only:

| File (lab: `run/<instance>/config/`) | Holds | Precedence |
|---|---|---|
| `config/users.json` (`auth.users_file.path`) | users written by administrators (Admin > Users > Users file) or by hand | wins over the database |
| `config/apikeys.json` (`config.apikeys.path`) | key records written by administrators (Admin > API keys > Keys file), by hand, and by SAJHA for keys marked persistent | checked before the database |
| `config/apikeys_db.json` (`auth.api_keys.db_dump_path`) | a dump of the database's keys, written every few minutes | used only when the database does not know a key or does not answer |

The lab copied `config/users.json.example` and `config/apikeys.json.example` into each instance. Look at
`run/risk-eu/config/apikeys.json`: the record `test-admin` (key `sja_test_admin_dev_key_0001`, owner
`testadmin`, role `admin`) is marked `"test_admin": true`, and `run/risk-eu/config/users.json` holds the
account `testadmin` / `testadmin-dev-1`, also marked. Signed in as an administrator with a console
session, the same files are on **Admin > API keys > Keys file** (`/admin/apikeys/file`) and **Admin >
Users > Users file** (`/admin/users/file`): keys masked, a new key shown once, passwords never shown.

### 2. What the test admin key does

While `sajhanet.test_admin_key.enabled` is on (the shipped setting, owner decision for development),
records marked `test_admin` sign in as an administrator, a **critical** notice ("Test admin key is
enabled") shows on every page, and each use is logged as a warning. Across a net it does more: **every**
forwarded call from this server carries the test admin key, whoever the caller is, and a host that holds
the same record with its own switch on runs the call as an administrator.

See it on the lab: call a tool on `cust-na` from `risk-eu`, then read `cust-na`'s audit:

```bash
curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  -H 'Content-Type: application/json' \
  -d '{"tool": "lab-net__cust-na__calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}}' > /dev/null
curl -s 'http://127.0.0.2:3003/api/audit/records?limit=1&event=net.host_call' -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; d=json.load(sys.stdin)['records'][0]['details']; print(d['identity'], d['key_id'], d['user'])"
```

```text
test_admin_key test-admin testadmin@risk-eu
```

The host ran the call as the test administrator. That is why the lab works without creating users and
keys on three instances; it is also why the test admin key is never for production.

### 3. Turn it off and call as yourself

Turn the switch off on all three. Create `run/local.yml`:

```yaml
sajhanet:
  test_admin_key:
    enabled: false
```

and restart the lab (`lab.sh stop`, then `lab.sh start`). The critical notice is gone, the test admin key
and account no longer sign in (`lab.sh status` now says it cannot show the members without it), and a
forwarded call carries **the caller's own key**: the key presented on the request, or, for a console
user, that user's default key, which the home keeps encrypted for exactly this. The host looks the key
up in its copy of the **net key directory** (every member publishes its users' keys as signed records,
never the keys themselves) and runs the call as the local account with the same login name, with that
account's roles there.

Sign in to `risk-eu` as `admin` / `admin123` and run a `cust-na` tool from the Tools page (the
filter **Remote (SAJHA Net)** lists them), or from the shell with a session token:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:3002/api/auth/login -H 'Content-Type: application/json' \
  -d '{"user_id": "admin", "password": "admin123"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -s -X POST http://127.0.0.1:3002/api/tools/execute -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"tool": "lab-net__cust-na__calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}}' | head -c 120; echo
```

`cust-na`'s `net.host_call` record (read it with a session token for `cust-na` the same way) now says
identity `api_key`, the key id of `risk-eu`'s `admin` default key, and user `admin@risk-eu`, mapped to
`cust-na`'s own `admin`. A user who exists only on `risk-eu` is refused at `cust-na` (`sajhanet.users.unknown:
refuse`, the default); [SAJHA Net](../architecture/SAJHA%20Net.md) section 11.3 describes links and role
maps.

On the build this tutorial was checked against, the same call made with an API key in `X-API-Key`
(instead of a session) was refused by the host with `key_unknown`: the home sent the key's name rather
than the key. A console session, or a `Bearer` session token as above, works.

Delete `run/local.yml` and restart to turn the test admin key back on for the later tutorials.

### 4. A per-member key

`sajhanet.peer_keys` names, per member, a key that calls to that member carry instead of the caller's
key or the test admin key. It is local configuration of the sending server, never published. The key is
one the **target** issued: the target checks it as one of its own keys, and the caller acts there as that
key's owner, with the key's tool access as a ceiling.

The lab already has such a key. Every instance's keys file, copied from `config/apikeys.json.example`,
holds the record `peer-key-from-home` with the key `sja_peer_b_sample_key_0001` (owner `testadmin`). Make
`risk-eu`'s calls to `cust-na` carry it: create `run/risk-eu/local.yml` with

```yaml
lab_env:
  SAJHA_SAJHANET_PEER_KEYS: '{"lab-net/cust-na": "sja_peer_b_sample_key_0001"}'
```

restart `risk-eu` (`lab.sh stop risk-eu`, `lab.sh start risk-eu`) and repeat the call of step 2:

```text
peer_key peer-key-from-home testadmin@risk-eu
```

`cust-na` recognised the key as its own (identity `peer_key`). A call to `treasury-eu` still carries the
test admin key. Keys are matched by `<net>/<instance>` or by `<instance>` alone, and a value may be a
`${ENV_NAME}` reference.

The lab passes the mapping as the environment variable `SAJHA_SAJHANET_PEER_KEYS` (JSON) because, on the
build this tutorial was checked against, the YAML map `sajhanet.peer_keys` in `application.yml` was not
read (calls kept carrying the test admin key). Delete `run/risk-eu/local.yml` and restart `risk-eu` to
undo.

## What you learned

- Users and keys live in the database; `config/users.json` and `config/apikeys.json` win over it, and
  `config/apikeys_db.json` is the fallback copy
- The test admin key makes every forwarded call arrive as an administrator, which suits a lab and nothing
  else
- With it off, the caller's own key travels and the host maps the caller to its own account of the same
  name
- A per-member key, issued by the target, replaces the caller's key toward that one member

## Next

- [Tutorial 31: Open Admission and the CA](TUTORIAL_31_open_admission_and_the_ca.md)
- Identity resolvers other than API keys: [Tutorial 37](TUTORIAL_37_reexport_and_bridges.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
