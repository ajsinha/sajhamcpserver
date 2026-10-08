# Tutorial 31: Open Admission and the CA

How does a SAJHA Net decide who may join? The shipped setting is **open admission**: no certificate
authority, each server makes its own self-signed certificate, and every member remembers the key it
first saw for each instance name, holding the name to that key from then on. The alternative is the
net's own **CA** (`builtin_ca`): one instance issues certificates against single-use enrollment tokens
and can revoke them. This tutorial runs both on the [local test lab](TUTORIAL_29_local_test_lab.md):
it provokes a name conflict in open mode, forgets a remembered key, then switches the lab to the CA,
enrolls two instances and revokes one. The design is [SAJHA Net](../architecture/SAJHA%20Net.md)
section 6; [Tutorial 28](TUTORIAL_28_build_a_sajha_net.md) does the CA with containers.

## What you'll learn

- What open admission trusts, where the first-use keys are kept and how a `name_conflict` looks
- How to forget a remembered key when a server was replaced on purpose, and what else that takes
- How to switch a net to its CA, issue enrollment tokens, enroll and revoke
- Why every member of a net uses the same admission mode

## Prerequisites

- The local test lab ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), freshly reset and started
- An administrator's credentials on each instance (the lab's test admin key will do)

## Steps

### 1. Open admission: first use

With the lab running, open **SAJHA Net > Net overview** on `risk-eu`. The Admission panel says "open:
self-signed certificates are accepted the first time a name is seen; then each name is held to that
key" and lists `cust-na` and `treasury-eu` with their key thumbprints and a **Forget** button each. The
same list is JSON:

```bash
curl -s http://127.0.0.1:3002/api/sajhanet/nets/lab-net/first-use -H 'X-API-Key: sja_test_admin_dev_key_0001'
```

The keys are kept on disk (`first_use.json` in the net's folder of `sajhanet.data_dir`), so a restart
does not forget them.

### 2. A name conflict

Pretend `cust-na`'s server was rebuilt: delete its folder, which holds its key, and start it again.

```bash
deployment/local-lab/lab.sh reset cust-na
deployment/local-lab/lab.sh start cust-na
```

It makes a new key and tries to join through `risk-eu`, which refuses: the name `cust-na` is already
held by another key. `lab.sh status` shows `cust-na` as "not joined", its console shows an error notice
"Name cust-na is held in lab-net", and its status names the holder:

```bash
curl -s http://127.0.0.2:3003/api/sajhanet/status -H 'X-API-Key: sja_test_admin_dev_key_0001' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['nets'][0]['refused']['detail'])"
```

```text
cust-na is already a member of lab-net with another key (Q0ZighvO...); an administrator can forget the old key if it was replaced
```

A refused server does not keep knocking: it stays out until its configuration or certificate changes.
This is what open admission protects: once a name is known, nobody else can take it. What it does not
protect is the first claim: any server that can reach a member and knows the net's name can join under an
unused name, and then receives forwarded calls (with the test admin key, while that is on). Use the CA
before a net spans machines you do not control.

### 3. Forget the old key

The rebuild was deliberate, so tell the members to forget the old key: **Forget** next to `cust-na` on
the Net overview of `risk-eu` and of `treasury-eu`, or:

```bash
for h in 127.0.0.1:3002 127.0.0.3:3004; do
  curl -s -X DELETE http://$h/api/sajhanet/nets/lab-net/first-use/cust-na -H 'X-API-Key: sja_test_admin_dev_key_0001'; echo
done
```

Each answers `{"net":"lab-net","forgotten":"cust-na"}` and audits `peer_key_forgotten`. On the build
this tutorial was checked against, forgetting was not enough by itself: the members still held the old
`cust-na` as a member record (state `left`, kept for `sajhanet.gossip.dead_retention_minutes`), and
learned the old key again from it. What worked was to forget the key on every member, restart them so
they drop the old record, clear the refusal the new server remembers (it is kept in its saved peer list,
`peers.json` in the net's folder), and start it:

```bash
deployment/local-lab/lab.sh stop
rm deployment/local-lab/run/cust-na/data/sajhanet/lab-net/peers.json
deployment/local-lab/lab.sh start
```

`cust-na` joins with its new key, and `first-use` on `risk-eu` now lists the new thumbprint. In a lab,
`lab.sh reset` (a new net) is the short way.

### 4. Switch the lab to the CA

All members of a net use one admission mode, so the switch is for all three. Reset the lab and set
`sajhanet.plugins.admission` in `run/local.yml`:

```bash
deployment/local-lab/lab.sh reset
mkdir -p deployment/local-lab/run
printf 'sajhanet:\n  plugins:\n    admission: builtin_ca\n' > deployment/local-lab/run/local.yml
deployment/local-lab/lab.sh start
```

`risk-eu` has no seeds, so it is a net of one and creates the net's CA at first start
(`sajhanet.ca_auto_init`, on by default); a notice asks you to back up the CA key, which never leaves
`risk-eu`. `cust-na` and `treasury-eu` start without a certificate and do not join; an error notice on each,
"Not joined to SAJHA Net lab-net", says how to enroll. Check the CA:

```bash
curl -s http://127.0.0.1:3002/api/sajhanet/nets/lab-net/ca -H 'X-API-Key: sja_test_admin_dev_key_0001' | head -c 300; echo
```

### 5. Enroll the other two

On the CA, create a single-use enrollment token for each name; on the new server, enroll with it,
giving the CA's URL:

```bash
K='X-API-Key: sja_test_admin_dev_key_0001'
for n in cust-na:127.0.0.2:3003 treasury-eu:127.0.0.3:3004; do
  name=${n%%:*}; hostport=${n#*:}
  token=$(curl -s -X POST http://127.0.0.1:3002/api/sajhanet/nets/lab-net/ca/tokens -H "$K" \
            -H 'Content-Type: application/json' -d "{\"instance\": \"$name\"}" \
          | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
  curl -s -X POST http://$hostport/api/sajhanet/nets/lab-net/enroll -H "$K" -H 'Content-Type: application/json' \
    -d "{\"ca_url\": \"http://127.0.0.1:3002\", \"token\": \"$token\"}"; echo
done
```

Each new server generates a key, sends a certificate request with the token, receives a certificate
valid for 30 days (`ca.cert_validity_days`; renewed by itself when a third remains) and joins through its
seed. Within seconds `lab.sh status` shows the three as alive, and the Net overview's Admission panel
shows the CA with the certificates it issued. With the command line client the same steps are
`sajha net ca enroll <name> --net lab-net` on the CA and `sajha net enroll --net lab-net --ca-url ...
--token ...` on the new server ([Command Line](../clients/Command%20Line.md)).

A token is for one name: the CA refuses a token for a name another certificate holds.

### 6. Revoke an instance

```bash
curl -s -X POST http://127.0.0.1:3002/api/sajhanet/nets/lab-net/ca/revoke \
  -H 'X-API-Key: sja_test_admin_dev_key_0001' -H 'Content-Type: application/json' \
  -d '{"instance": "treasury-eu", "reason": "tutorial"}'
```

The signed revocation list (now version 2) spreads by gossip; `risk-eu` and `cust-na` drop
`treasury-eu` and its tools within seconds, and `treasury-eu` sees the others as suspect. Revoking one
certificate by serial (a lost key) is `{"serial": "..."}` instead.

### 7. Back to open mode

```bash
deployment/local-lab/lab.sh reset
rm deployment/local-lab/run/local.yml
deployment/local-lab/lab.sh start
```

The third mode, `manual`, pins each peer's certificate thumbprint by hand (`identity.pins` in a net
entry, or `POST /api/sajhanet/nets/{net}/pins`); [SAJHA Net](../architecture/SAJHA%20Net.md) section 6.5
describes it.

## What you learned

- Open admission accepts a self-signed certificate the first time a name is seen and holds the name to
  that key; a second key for the name is a loud `name_conflict`
- Forgetting a key is an administrator's deliberate act; a refused server waits until its configuration
  or certificate changes
- The CA issues certificates against single-use tokens, renews them and revokes them; its key never
  leaves the CA instance
- One net, one admission mode

## Next

- [Tutorial 32: The SAJHA Net Console](TUTORIAL_32_the_sajha_net_console.md)
- Admission for a server that is not SAJHA: [SAJHA Net Agent](../clients/SAJHA%20Net%20Agent.md) section 3

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
