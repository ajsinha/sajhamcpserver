# SAJHA Net demo: three instances in one net

Three SAJHA containers, `risk-eu`, `cust-na` and `treasury-na`, in the net `demo-net`. `risk-eu` is
the founder and CA instance (no seeds); the other two list it as their seed. The demo runs the
`builtin_ca` admission mode (`SAJHA_SAJHANET_PLUGINS_ADMISSION`; the shipped default is `open`), so a
smoke script initialises the CA, enrolls the other two with enrollment tokens, waits until the three see
each other, and calls one of `cust-na`'s tools on `risk-eu`.

**This is a lab.** Traffic between the containers is plain HTTP (`SAJHA_SAJHANET_REQUIRE_HTTPS=false`),
and the smoke script signs in with the test admin key from `config/apikeys.json.example`, which the
compose file mounts as each container's `config/apikeys.json`; with the test admin key on, every call
between the three carries it and runs as an administrator at the host. Never run a net like this
anywhere else. The guide is [SAJHA Net](../../docs/architecture/SAJHA%20Net.md); the walkthrough is
[Tutorial 28](../../docs/tutorials/TUTORIAL_28_build_a_sajha_net.md).

## Run it

```bash
docker compose -f deployment/sajhanet-demo/docker-compose.yml -p sajhanet-demo up -d --build
python3 deployment/sajhanet-demo/smoke.py
```

The script prints one `ok` line per step and `PASS` at the end (exit status 0). It is idempotent: run it
again and it skips the CA and the enrollments.

| Instance | On the host | Inside the demo network | Role |
|---|---|---|---|
| `risk-eu` | http://127.0.0.1:3201 | `http://sajha-risk-eu:3002` | founder, CA instance |
| `cust-na` | http://127.0.0.1:3202 | `http://sajha-cust-na:3002` | seed: `risk-eu` |
| `treasury-na` | http://127.0.0.1:3203 | `http://sajha-treasury-na:3002` | seed: `risk-eu` |

Each instance exports its `calc_*` tools to the others and imports everything they export. Sign in to
any of them in a browser and open **SAJHA Net > Instances** to see the three, and the tools each offers
you; the navbar shows `Net · <instance name>`.

Try a call across by hand:

```bash
curl -s -X POST http://127.0.0.1:3201/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "demo-net__cust-na__calc_percentage_change", "arguments": {"old_value": 100, "new_value": 125}}'
```

The answer's `_meta["io.sajha/net"].instance` is `cust-na`.

## Stop it

```bash
docker compose -f deployment/sajhanet-demo/docker-compose.yml -p sajhanet-demo down -v
```

The data lives in the containers (no volumes), so `down` discards the CA key and the certificates: the
next `up` starts a new net.
