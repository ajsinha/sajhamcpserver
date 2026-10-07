# Tutorial 28: Build a SAJHA Net

SAJHA Net joins SAJHA servers into a net: they find each other by gossip, prove who they are with
certificates from the net's own CA, and each offers its tools to the others, so a user on one instance
can call a tool that runs on another, as themselves. Here you run three instances on one machine,
`risk-eu`, `cust-na` and `treasury-na`, in a net called `demo-net`: you start the first as a net of one,
make it the net's CA, enroll the other two, call a tool across, block a caller, and see which key a
forwarded call carries. The design is [SAJHA Net](../architecture/SAJHA%20Net.md); the wire protocol is
the [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md).

## What you'll learn

- How a net entry is configured, and why a server with no seeds is a net of one
- How the CA instance issues enrollment tokens and how an instance enrolls and joins through a seed
- How to see the net from the console: the Instances page and the navbar badge
- How a call to a remote tool travels, and which API key it carries
- How to block a caller, and what the caller sees
- What the test admin key and per-member keys are for, and why neither belongs in production

## Prerequisites

- Docker with Compose, and a SAJHA checkout ([Tutorial 1](TUTORIAL_01_getting_started.md))
- An idea of API keys and roles ([Security Model](../security/Security%20Model.md))

The three instances run from `deployment/sajhanet-demo/`. It is a **lab**: traffic between the
containers is plain HTTP (`SAJHA_SAJHANET_REQUIRE_HTTPS=false`) and the test admin key from
`config/apikeys.json.example` is mounted into each container.

## Steps

### 1. Read the three net entries

Open `deployment/sajhanet-demo/docker-compose.yml`. Each service sets `SAJHA_SAJHANET_ENABLED=true` and
one net entry in `SAJHA_SAJHANET_NETS` (the same shape as `sajhanet.nets` in `config/application.yml`):

```json
[{"name": "demo-net", "instance_name": "risk-eu", "founder": true, "ca": {"enabled": true},
  "export": [{"tools": ["calc_*"]}], "import": [{"tools": ["*"]}]}]
```

`cust-na` and `treasury-na` differ in their name and in `"seeds": ["http://sajha-risk-eu:3002"]`. The
`export` rule offers the `calc_*` tools to the other members; `import` lets this server's users use
whatever the others offer. Nothing is exported or imported without a rule. `SAJHA_SAJHANET_BASE_URL` is
the URL peers reach each server on, and `SAJHA_SAJHANET_ALLOWED_NETWORKS` admits the demo's private
network to the peer-address check.

`risk-eu` lists no seeds. A net entry with no seeds is a **net of one**: the server is the net's
founder and only member, it raises no error, retries nothing and sends nothing, and it grows into an
ordinary net when someone joins through it.

### 2. Start the three

```bash
docker compose -f deployment/sajhanet-demo/docker-compose.yml -p sajhanet-demo up -d --build
```

They answer on http://127.0.0.1:3201 (`risk-eu`), 3202 (`cust-na`) and 3203 (`treasury-na`). Sign in to
`risk-eu` and look at the navbar: beside the SAJHA wordmark the badge reads **Net · risk-eu**, with a
grey dot (a net of one). It links to **SAJHA Net > Instances**, which lists `risk-eu` alone, as alive.
`cust-na` and `treasury-na` are not in the net yet: they have no certificate, and their SAJHA Net admin
page (**Admin > SAJHA Net**) says how to enroll.

Every server is listed on its own Instances page, even with SAJHA Net off: a SAJHA that is in no net is
a net of one too.

### 3. Make risk-eu the net's CA

The CA's key never leaves the CA instance. Create it once, on `risk-eu`:

```bash
sajha -s http://127.0.0.1:3201 -k sja_test_admin_dev_key_0001 net ca init --net demo-net
```

(`POST /api/sajhanet/nets/demo-net/ca/init` does the same; `-k` signs the command line in with the test
admin key, step 7.) `risk-eu` now has its own certificate and has joined `demo-net`, still alone.

### 4. Enroll the other two

On the CA, create a single-use enrollment token for each name:

```bash
sajha -s http://127.0.0.1:3201 -k sja_test_admin_dev_key_0001 net ca enroll cust-na --net demo-net
```

It prints the token and the command to run on the new server. Give it the CA's URL as the containers
see it:

```bash
sajha -s http://127.0.0.1:3202 -k sja_test_admin_dev_key_0001 net enroll --net demo-net \
    --ca-url http://sajha-risk-eu:3002 --token <token>
```

`cust-na` generates a key, sends a certificate request with the token, receives its certificate and
joins through its seed. Do the same for `treasury-na`. A token is for one name: the CA refuses a token
for a name another certificate already holds, and every member refuses a server claiming such a name
(`name_conflict`).

Or let the smoke script do steps 3 and 4 and check the result:

```bash
python3 deployment/sajhanet-demo/smoke.py
```

### 5. Watch the net form

Within a few seconds gossip has spread the news. On any of the three, **SAJHA Net > Instances** lists all
three as alive, with region, labels, when each was last seen and how many of its tools you may use from
here; the navbar badge turns green. Open `cust-na` from the list: its `calc_*` tools are there with
their qualified names (`demo-net__cust-na__calc_percentage_change`), inputs and outputs, health and
latency, and a **Try it** button that opens the Tools page's form for the proxy tool.

The same from the command line:

```bash
sajha -s http://127.0.0.1:3201 -k sja_test_admin_dev_key_0001 net status
```

Administrators also have **SAJHA Net > Remote tools**: the host and tool table, with each row's state,
trust, contract hash and place in the resolution order. `risk-eu` has its own `calc_percentage_change`,
so the plain name stays local; the qualified name goes to `cust-na`.

### 6. Call a tool across

```bash
curl -s -X POST http://127.0.0.1:3201/api/tools/execute \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"tool": "demo-net__cust-na__calc_percentage_change", "arguments": {"old_value": 100, "new_value": 125}}'
```

The answer is `cust-na`'s, and `_meta["io.sajha/net"]` names the instance and the trace id. What
happened: `risk-eu` (the **home**) checked that you may use the proxy, signed a forwarded `tools/call`
with its certificate and sent it to `cust-na` (the **host**) with an API key in `Sajha-Net-Api-Key`.
`cust-na` verified the signature, looked the key up in its copy of the net key directory, checked that
the key came from its home, mapped its owner to a local user, and ran the tool under its own access
rules and policies, as that user.

### 7. Which key travels

A forwarded call carries exactly one API key, chosen in this order:

1. **A per-member key** set for the target in `sajhanet.peer_keys` (`"demo-net/cust-na": "sja_..."`, or
   a `${ENV}` reference). It is local configuration, never published, and works only when the target's
   own `config/apikeys.json` has a record with the same key. Use it when one member has issued your
   server a key of its own.
2. **The test admin key**, while `sajhanet.test_admin_key.enabled` is on and this server's
   `config/apikeys.json` has a record marked `"test_admin": true`. That is what the demo uses: every
   call arrives at the host as the test administrator. A critical notice shows on every page while it
   is on; it is for development and tests only.
3. **The caller's own key**: the key they presented on this request, or, for a console user, their
   default key from the vault. The host verifies it against the key directory and runs the call as the
   local account with the same login name (or a linked one), with that account's roles there.

To see the third case, turn the test admin key off on all three
(`SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED=false`), create a user `alice` on `risk-eu` and on `cust-na`
(**Admin > Users**), give her a key on `risk-eu` (**My API keys**, signed in as alice), and call the
tool with her key: it runs on `cust-na` as `cust-na`'s alice, with her roles there. A role there without
access to the tool is refused there, whatever `risk-eu` allows.

### 8. Block a caller

Blocks are local decisions of one instance. On `cust-na`, refuse everything `risk-eu` sends:

```bash
curl -s -X POST http://127.0.0.1:3202/api/sajhanet/nets/demo-net/blocks \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"level": "inbound", "target_instance": "risk-eu", "reason": "tutorial"}'
```

The answer's `effect` says what changes. Repeat the call of step 6: it now comes back with
`isError: true` and `_meta["io.sajha/net"].refusal` naming the reason and the instance that refused. A
call by plain name would move on to the next host offering the tool; a call by qualified name never
does. Remove the block with `DELETE /api/sajhanet/nets/demo-net/blocks/<id>` (the id is in the answer,
and in **Admin > SAJHA Net**). Blocks can also name one tool, one remote user (`alice@risk-eu`), the
other direction, or a whole instance, and can expire.

### 9. Stop the net

```bash
docker compose -f deployment/sajhanet-demo/docker-compose.yml -p sajhanet-demo down
```

The containers keep their data inside, so the next `up` starts a new net.

## What you learned

- A net entry names the net, this server's name in it, its seeds and its export and import rules; with
  no seeds the server is a net of one that grows when others join through it
- The CA instance issues single-use enrollment tokens; an enrolled instance joins through its seed and
  gossip does the rest
- The Instances page and the navbar badge show which instance you are on and what each offers you
- A forwarded call is signed by the home and carries one API key; the host verifies it and decides for
  itself
- Blocks are local, audited and immediate; per-member keys and the test admin key are configuration,
  and the test admin key is never for production

## Next

- How catalogs, resolution, fallback and one name one contract work: [SAJHA Net](../architecture/SAJHA%20Net.md)
  sections 7 to 9
- The keys and their defaults: [Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)
- Nets on Kubernetes: [Kubernetes Deployment](../getting-started/Kubernetes%20Deployment.md#sajha-net)
- This is the last tutorial; the [documentation index](../README.md) lists every guide
