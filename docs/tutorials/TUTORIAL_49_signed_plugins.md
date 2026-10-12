# Tutorial 49: Signed Plugins and the Plugin Catalog

A plugin is a folder of tools (and optionally Python code) that SAJHA loads at start-up. Loading runs
its code in the server, so SAJHA wants to know who wrote it and that nobody changed it since. This
tutorial plays both parts: as a **publisher** you create a key, sign a plugin and pack it for a catalog;
as an **administrator** you trust the publisher's key, review the package in the plugin catalog, install
it through the review-and-approve gate, and watch SAJHA refuse a tampered and an unsigned plugin.
Signatures, verdicts and the catalog are owned by
[Security Model](../security/Security%20Model.md#plugins); the review-and-approve gate is the one of
[Tool Generation](../architecture/Tool%20Generation.md) §6.

**What was verified.** Every step below was run as written from a checkout, with a scratch SQLite
database (`SAJHA_DB_PATH`), cache directory (`SAJHA_CACHE_DIR`) and directory for loaded results
(`SAJHA_BI_SCRATCH_DIR`), and the default offline mock LLM provider; the plugin folder, trusted-key folder
and catalog source were scratch folders, so nothing was written under `config/`. The outputs are from that
run; keys, key ids, hashes and review ids are your own.

## What you'll learn

- The publisher's commands: `keygen`, `sign`, `verify`, `pack`
- The four verdicts (`trusted`, `invalid`, `unsigned`, `untrusted`) and what each means for loading
- How the catalog lists packages, and how a review binds an install to one package
- What `plugins.allow_unsigned: false` changes at start-up

## Prerequisites

- A checkout with its virtual environment ([Quick Start](../getting-started/Quick%20Start.md)), including
  the `cryptography` package (in `requirements.txt`), and the development API key
  `sja_test_admin_dev_key_0001` from `config/apikeys.json` (role `admin`).
- Run the publisher commands from the checkout (`python -m sajha.core.plugin_signing`).

## 1. As the publisher: a key pair

```bash
P=/tmp/t49; mkdir -p $P/publisher $P/src/acme-savings/tools $P/catalog $P/plugins $P/plugin_keys
.venv/bin/python -m sajha.core.plugin_signing keygen --publisher acme --out $P/publisher
```

```text
wrote /tmp/t49/publisher/acme.key (keep it secret) and acme.pub (key id 442e7700b3a5aec8)
```

`acme.key` is written readable by you only. Keep it off the server; `acme.pub` is what administrators
trust.

## 2. As the publisher: a plugin, signed and packed

A plugin is a folder with a `plugin.json` manifest and a `tools/` folder of tool configurations (and
`.py` files defining `BaseMCPTool` classes, if it ships code). This one offers one tool built on SAJHA's
compound-interest implementation:

```bash
cat > $P/src/acme-savings/plugin.json <<'EOF'
{"name": "acme-savings", "version": "1.0.0", "author": "Acme Treasury",
 "description": "Savings growth calculator for the treasury desk", "min_sajha_version": "8.0.0"}
EOF
python3 - $P/src/acme-savings <<'EOF'
import json, sys
src = json.load(open('config/tools/calc/calc_compound_interest.json'))
tool = {k: src[k] for k in ('implementation', 'annotations', 'inputSchema')}
tool.update(name='acme_savings_growth', enabled=True,
            description='Savings growth with monthly compounding (Acme Treasury plugin). Returns future_value and total_interest.')
json.dump(tool, open(sys.argv[1] + '/tools/acme_savings_growth.json', 'w'), indent=2)
EOF
.venv/bin/python -m sajha.core.plugin_signing sign --key $P/publisher/acme.key --publisher acme $P/src/acme-savings
.venv/bin/python -m sajha.core.plugin_signing verify --trusted $P/publisher/acme.pub $P/src/acme-savings
.venv/bin/python -m sajha.core.plugin_signing pack --out $P/catalog $P/src/acme-savings
```

```text
signed acme-savings 1.0.0: 2 file(s), key 442e7700b3a5aec8
trusted: signed by acme (key 442e7700b3a5aec8, plugins.trusted_keys)
/tmp/t49/catalog/acme-savings-1.0.0.zip
```

`sign` writes `plugin.sig`: the SHA-256 of every other file, the plugin's name and version, and an
Ed25519 signature over them:

```text
{
  "algorithm": "ed25519",
  "files": {
    "plugin.json": "sha256:76419867e08aba2c1aec8c1e5ea89e925c47158634b8f4c2f33764965d4b6c14",
    "tools/acme_savings_growth.json": "sha256:e3451730a66ae79f7a01aabb89acbdaa9a40fdcf496faff9010961dad79f6751"
  },
  "format": "sajha-plugin-signature/1",
  "key_id": "442e7700b3a5aec8",
  "plugin": "acme-savings",
  "publisher": "acme",
  "signature": "g1JePcqXJbB44HwswCYdg+VnEo4DJDc/pqnymLt093IUa0uQqZnOUWgtrFo0RWaNF21KeVs2eLfhU/KJawHgBw==",
  "version": "1.0.0"
}
```

To have something to refuse later, put two more packages in the catalog folder: a copy of the plugin
with one file changed after signing, and a plugin with no signature at all:

```bash
cp -r $P/src/acme-savings $P/catalog/acme-savings-tampered
sed -i 's/monthly compounding/daily compounding/' $P/catalog/acme-savings-tampered/tools/acme_savings_growth.json
mkdir -p $P/catalog/desk-notes/tools
echo '{"name": "desk-notes", "version": "0.1.0", "author": "Someone", "description": "Unsigned example", "min_sajha_version": "8.0.0"}' \
  > $P/catalog/desk-notes/plugin.json
python3 -c "
import json; t=json.load(open('$P/src/acme-savings/tools/acme_savings_growth.json')); t['name']='desk_notes_growth'
json.dump(t, open('$P/catalog/desk-notes/tools/desk_notes_growth.json','w'))"
```

## 3. As the administrator: the catalog

Point SAJHA at the catalog folder, and keep this tutorial's plugin folder and trusted keys apart from
`config/` (normally they are `config/plugins` and `config/plugin_keys`):

```bash
export SAJHA_DB_PATH=$P/t49.db SAJHA_CACHE_DIR=$P/cache SAJHA_BI_SCRATCH_DIR=$P/scratch \
  SAJHA_CONFIG_PLUGINS_DIR=$P/plugins SAJHA_PLUGINS_TRUSTED_KEYS_DIR=$P/plugin_keys \
  SAJHA_PLUGINS_CATALOG_SOURCES=$P/catalog
.venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195
```

`plugins.catalog.sources` may also name `storage:<prefix>` on the storage backend, or a remote
`https://.../index.json` fetched through the outbound fetch guard. The console page is **Plugin catalog**
(Admin, Manage; `/admin/plugins/catalog`); its JSON:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
curl -s http://127.0.0.1:3195/api/plugins/catalog -H "$K" | python3 -c "
import json,sys; d=json.load(sys.stdin); print('trusted_publishers', d['trusted_publishers'], 'allow_unsigned', d['allow_unsigned'])
for p in d['packages']: print(p['ref'], p['status'], '|', p['detail'])"
```

```text
trusted_publishers [] allow_unsigned True
acme-savings-1.0.0.zip untrusted | signed by acme with key 442e7700b3a5aec8, which is not a configured trusted key
acme-savings-tampered invalid | the files are not the signed ones (changed: tools/acme_savings_growth.json)
desk-notes unsigned | the plugin has no publisher signature (plugin.sig)
```

## 4. Trust the publisher

Trusted keys are `<publisher>.pub` files in `plugins.trusted_keys_dir` (read on every check, no restart)
or `<publisher>=<key>` entries in `plugins.trusted_keys`:

```bash
cp $P/publisher/acme.pub $P/plugin_keys/
curl -s http://127.0.0.1:3195/api/plugins/catalog -H "$K" | python3 -c "
import json,sys; d=json.load(sys.stdin); print('trusted_publishers', d['trusted_publishers'])
for p in d['packages']: print(p['ref'], p['status'])"
```

```text
trusted_publishers ['acme']
acme-savings-1.0.0.zip trusted
acme-savings-tampered invalid
desk-notes unsigned
```

The tampered copy names the same publisher and key, but one of its files is not the signed one.

## 5. Review, then approve and install

**Review** fetches and verifies the package, keeps it bound to its package hash, and shows the manifest,
the signature and every file:

```bash
curl -s -X POST http://127.0.0.1:3195/api/plugins/catalog/review -H "$K" -H 'Content-Type: application/json' \
  -d '{"source":"'$P/catalog'","ref":"acme-savings-1.0.0.zip"}' | python3 -c "
import json,sys; d=json.load(sys.stdin)
print('id', d['id']); print('hash', d['hash']); print('signature', d['signature']['status'], d['signature']['publisher'])
for f in d['files']: print('file', f['path'], f['bytes'])"
```

```text
id 2a32442f68eca15e
hash 804d2f591bf98a78f8a26c06d41a5a976b7dea2ff3c26011223ae5f0c8b13b21
signature trusted acme
file plugin.json 169
file tools/acme_savings_growth.json 1087
file plugin.sig 505
```

Installing needs the review id, the hash you reviewed, and explicit approval:

```bash
R=2a32442f68eca15e; H=804d2f591bf98a78f8a26c06d41a5a976b7dea2ff3c26011223ae5f0c8b13b21
install() { curl -s -X POST http://127.0.0.1:3195/api/plugins/catalog/install -H "$K" -H 'Content-Type: application/json' -d "$1"; echo; }
install '{"review":"'$R'","hash":"'$H'"}'
install '{"review":"'$R'","hash":"'${H/8/9}'","approve":true}'
install '{"review":"'$R'","hash":"'$H'","approve":true}' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['message'], d['installed'])"
```

```text
{"success":false,"error":"an install needs explicit approval (approve: true) after you have reviewed the files"}
{"success":false,"error":"the package is not the one you reviewed; review it again","hash":"804d2f591bf98a78f8a26c06d41a5a976b7dea2ff3c26011223ae5f0c8b13b21"}
Installed acme-savings 1.0.0: 1 tool(s) registered. {'at': 1791783291.2168112, 'by': 'testadmin', 'hash': '804d2f591bf98a78f8a26c06d41a5a976b7dea2ff3c26011223ae5f0c8b13b21', 'files': 3, 'tools': 1, 'replaced': False, 'approval': None}
```

At install SAJHA fetched the package again and checked it still had the reviewed hash and was still
trusted, and asked the policy engine about the pseudo tool call `studio.deploy` with
`{"tool": "plugin:acme-savings", "kind": "plugin"}`; a `require_approval` rule there would have sent the
install to the Approvals page (`approval` would say so). The files are now in the plugins folder and the
tool is registered:

```bash
.venv/bin/python call.py acme_savings_growth '{"principal": 10000, "rate": 5, "years": 10}' 2>/dev/null
```

```text
{
  "principal": 10000,
  "rate": 5,
  "years": 10,
  "future_value": 16470.09,
  "total_interest": 6470.09
}
```

(`call.py` is the one-tool MCP helper of [Tutorial 48](TUTORIAL_48_sandbox_egress.md), printing the text
content when a tool returns no structured content.) The review and the install are audit entries,
`plugins.catalog.review` and `plugins.catalog.install`, with the plugin, version, publisher, key id and
hash.

Only a `trusted` package can be installed from the catalog, whatever `plugins.allow_unsigned` says:

```bash
for ref in acme-savings-tampered desk-notes; do
  curl -s -X POST http://127.0.0.1:3195/api/plugins/catalog/review -H "$K" -H 'Content-Type: application/json' \
    -d '{"source":"'$P/catalog'","ref":"'$ref'"}' | python3 -c "import json,sys; print(json.load(sys.stdin)['error'])"
done
```

```text
only a plugin signed by a trusted publisher can be installed from the catalog: invalid: the files are not the signed ones (changed: tools/acme_savings_growth.json)
only a plugin signed by a trusted publisher can be installed from the catalog: unsigned: the plugin has no publisher signature (plugin.sig)
```

## 6. The gate at start-up

Plugins placed in the plugins folder by hand are checked every time SAJHA loads them. Stop SAJHA, change
a file of the installed plugin, copy the unsigned one in, and start again with
`plugins.allow_unsigned: false`:

```bash
sed -i 's/monthly compounding/daily compounding/' $P/plugins/acme-savings/tools/acme_savings_growth.json
cp -r $P/catalog/desk-notes $P/plugins/
SAJHA_PLUGINS_ALLOW_UNSIGNED=false .venv/bin/python run_sajha_web.py --host 127.0.0.1 --port 3195
```

```bash
curl -s http://127.0.0.1:3195/api/notices -H "$K" | python3 -c "
import json,sys
for n in json.load(sys.stdin)['notices']:
    if n['id'].startswith('plugins.'): print(n['id'], n['severity'], '|', n['detail'])"
```

```text
plugins.signature:acme-savings error | publisher signature invalid: the files are not the signed ones (changed: tools/acme_savings_growth.json)
plugins.signature:desk-notes error | the plugin has no publisher signature (plugin.sig); refused because plugins.allow_unsigned is false
```

Neither plugin's tools are registered. A tampered plugin is refused whatever the setting; an unsigned or
untrusted one is refused only with `allow_unsigned: false`, and otherwise loads with the warning notice
`plugins.unsigned:<name>`. `allow_unsigned` defaults to `true` so that plugins installed before signatures
existed keep loading; set it to `false` once yours are signed.

A signature says who wrote a plugin, not that its code is safe: trust only publishers whose code you would
run in the server.

## Summary

- Publishers run `python -m sajha.core.plugin_signing keygen | sign | verify | pack`; the private key never
  goes to the server
- Administrators trust a publisher by placing its `.pub` in `plugins.trusted_keys_dir` (or
  `plugins.trusted_keys`)
- The plugin catalog lists `plugins.catalog.sources` with a verdict per package and installs only trusted
  ones, through a review bound to the package hash, explicit approval and the policy engine's
  `studio.deploy`
- At load, a tampered plugin is always refused; unsigned and untrusted ones depend on
  `plugins.allow_unsigned`

## Next

- Plugins, signatures and the catalog in full: [Security Model](../security/Security%20Model.md#plugins)
- [Tutorial 50: Provider Packs](TUTORIAL_50_provider_packs.md)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
