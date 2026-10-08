# Tutorial 38: The SAJHA Net Conformance Runner

The SAJHA Net Protocol lists numbered conformance cases (protocol section 20), each for one or more
targets: a SAJHA instance (S), an agent-fronted server (A), a library (L). The conformance runner checks
a live participant against them over HTTP, as a participant that never joins, and checks the protocol
core of this checkout against the test vectors. This tutorial runs it against the three instances of the
[local test lab](TUTORIAL_29_local_test_lab.md), a sponsored member, an agent and the library. The
protocol is [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md); the runner is described in
[SAJHA Net Agent](../clients/SAJHA%20Net%20Agent.md) section 9.

## What you'll learn

- How to run the suite against a URL, a sponsored participant and the library
- How to read the report: `PASS`, `FAIL`, `SKIP` and why a case is skipped
- What the runner needs in each admission mode

## Prerequisites

- The local test lab running in open admission ([Tutorial 29](TUTORIAL_29_local_test_lab.md))
- For sections 3 and 4, the sponsored member and agent of [Tutorial 34](TUTORIAL_34_sponsor_a_server_and_the_net_agent.md)

## Steps

### 1. Against a SAJHA instance

```bash
python -m sajha.net.conformance --target http://127.0.0.1:3002 --net lab-net --allow-plain-http
```

```text
SAJHA Net conformance: risk-eu (target S, kind sajha) in lab-net
  NAME-01  SKIP  a library case: run with --target library
  ...
  NAME-06  PASS
  NAME-07  SKIP  in-process only: tests/net/test_net_membership.py
  ...
  CALL-13  SKIP  the target does not advertise reexport
  FB-01    PASS
  ERR-01   PASS
  LIM-01   PASS
36 passed, 0 failed, 65 skipped
```

It takes about a second. The runner made itself a self-signed identity, which an open-admission net
accepts, and sent the target signed, tampered and oversized requests on `/sajhanet/v1/` and the signed
MCP endpoint, checking every answer against the protocol. The exit status is 1 when a case fails;
`--json` prints the report as data, `--only CALL-01,SIG-03` runs some cases.

### 2. Read the skips

Every id of section 20 is reported, so most lines on one target are skips, each with its reason:

- **a library case**: it checks the protocol core itself; run `--target library`;
- **in-process only**: it needs the target's insides (its clock, its CA administration, several failing
  members); the report names the file of SAJHA's own test suite that covers it;
- **the target does not advertise ...**: the case is for a feature the target does not offer (the lab
  does not turn on `reexport` or `token_exchange`; [Tutorial 37](TUTORIAL_37_reexport_and_bridges.md)
  does, and the corresponding cases then run).

`--api-key <key>` adds CALL-01, a real call with the key of a user the target accepts; `--tool` picks the
tool it calls (default: the first in the target's catalog).

### 3. Against a sponsored member

A sponsored participant shares its sponsor's URL, so name it:

```bash
python -m sajha.net.conformance --target http://127.0.0.2:3003 --net lab-net --instance units-svc --allow-plain-http
```

```text
32 passed, 0 failed, 69 skipped
```

### 4. Against an agent, and the library

```bash
python -m sajha.net.conformance --target http://127.0.0.4:3011 --net lab-net --allow-plain-http
python -m sajha.net.conformance --target library
```

```text
36 passed, 0 failed, 65 skipped
18 passed, 0 failed, 83 skipped
```

The library cases run the protocol core of this checkout (`sajha/net/`) against the vectors of protocol
section 21: names, canonical JSON, signatures and digests. A third-party implementation of the protocol
claims conformance as target A or L with the same runner.

### 5. In a net with a CA

In `builtin_ca` admission a self-signed runner is refused. Create an enrollment token for the runner's
name on the CA instance ([Tutorial 31](TUTORIAL_31_open_admission_and_the_ca.md), step 5) and pass it:

```bash
python -m sajha.net.conformance --target http://127.0.0.1:3002 --net lab-net --name conformance-1 \
  --ca-url http://127.0.0.1:3002 --token <token> --identity-dir /tmp/conformance-id --allow-plain-http
```

```text
37 passed, 0 failed, 64 skipped
```

The token is spent on first use; `--identity-dir` keeps the runner's key and certificate, so later runs
reuse them under the same `--name`. In an open net, the same two options keep the runner from appearing
under a new name each time.

## What you learned

- `python -m sajha.net.conformance --target <url> --net <net>` checks a live participant from outside;
  `--instance` names a sponsored one; `--target library` checks the protocol core
- A skip always says why: another target's case, a case for the target's insides (with the test file
  that covers it), or a feature the target does not advertise
- In an open net the runner's self-signed identity is accepted; in a CA net it enrolls with a token

## Next

- [Tutorial 39: Console Single Sign-On](TUTORIAL_39_console_single_sign_on.md)
- The cases and what each requires: [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md) section 20

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
