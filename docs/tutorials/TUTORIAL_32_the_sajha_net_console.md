# Tutorial 32: The SAJHA Net Console

The console shows a SAJHA Net from where you stand: which instance you are on, who else is in the net
and in what state, which remote tools you may use and where they run, how this server admits others,
and what needs a person. This tutorial is a guided tour of those pages on the
[local test lab](TUTORIAL_29_local_test_lab.md), with a crash and a block along the way so the pages
have something to show. The pages are described in [SAJHA Net](../architecture/SAJHA%20Net.md)
section 17; the console as a whole in [Architecture](../architecture/Architecture.md) section 10.

## What you'll learn

- What the navbar badge says and where it leads
- How to read the Instances page and an instance's page, and run a remote tool from there
- What Your net access tells a user who is not an administrator
- How to read the Net overview: membership, topology map, admission panel, notices, recent calls
- What the Remote tools page and the SAJHA Net admin page are for

## Prerequisites

- The local test lab running ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), signed in to `risk-eu`
  (http://127.0.0.1:3002) as `testadmin` / `testadmin-dev-1`

## Steps

### 1. The badge

Beside the SAJHA wordmark the badge reads **Net · risk-eu**: the instance name this server has in its
first net, with a health dot. Hover it: "lab-net: risk-eu (joined; 3 instances)". The dot is green when
every member is alive, grey for a net of one, amber when some members are suspect or dead, and red when
this server has not joined or its name is in conflict; the words are on hover. With several nets the
badge adds `+N` and shows the worst state. It links to the Instances page, and the **SAJHA Net**
menu holds the rest: Instances and Your net access for everyone, Net overview, Remote tools and SAJHA
Net admin for administrators.

### 2. Instances

**SAJHA Net > Instances** (`/net/instances`) lists this server first, marked THIS SERVER, then every
participant of its nets: net, name, kind (`sajha`, `agent`, `sponsored`), vendor, state, region, labels,
when it was last seen, and how many of its tools you may use from here. Search and filters narrow the
list by net, state, kind, region and label. Even with SAJHA Net off, the page lists this server: a
server in no net is a net of one.

Open `cust-na` (`/net/instances/lab-net/cust-na`): its tools with their qualified names, plain-name
alias, description, inputs and outputs, health and latency, and a **Try it** button that opens the Tools
page's form for the proxy tool. `/net/instances/this` is this server's own page. The data behind both is
`GET /api/sajhanet/instances`.

### 3. Your net access

**SAJHA Net > Your net access** (`/net/access`) is for every user, not only administrators: every tool
other instances offer through this server, grouped by net, with each host in resolution order, whether
**you** may use it, and a Try it button per host. A tool this server also has locally says so ("this
server has its own calc_beta; the plain name calls it"); a remote-only tool shows its plain name
(`calc_loan_amortization`, `calc_retirement`). This server decides what it lists for you; the host
checks your access again on every call, so a tool listed as usable can still be refused there.

### 4. The Net overview

**SAJHA Net > Net overview** (`/admin/sajhanet/overview`) is one net at a glance.

- **Tiles**: membership (healthy, joined, how many members alive), instances, admission mode, remote
  tools active or held, and how many notices need a person.
- **Topology**: a map of the instances (dots coloured by state: alive, suspect, dead or blocked, left)
  with lines for the tools one offers another, dashed lines for re-exports and thicker lines for calls
  observed since start. **Pause live view** stops the refresh; **The map as a table** shows the same
  edges as rows for screen readers and small screens. The data is `GET /api/sajhanet/topology`.
- **Members**: each instance's state, vendor, region and last seen, and below it the gossip agent, this
  server's certificate, incarnation, revocation list version and seeds ("none (a founder)" on `risk-eu`).
- **Notices, conflicts and held tools**: the SAJHA Net notices (the lab shows "SAJHA Net lab-net allows
  plain HTTP"), quarantined tools and tools waiting for review.
- **Blocks**: blocks set here and blocks others published naming this server.
- **Admission**: in open mode the first-use keys with **Forget** buttons
  ([Tutorial 31](TUTORIAL_31_open_admission_and_the_ca.md)); in manual mode the pins; with the CA, the
  CA and its certificates.
- **Recent forwarded calls**, **Call-chain refusals** and **Residency decisions**, from the audit chain,
  each with its trace id. The data is `GET /api/sajhanet/overview`.

### 5. Watch it change

Crash `cust-na` and keep the overview open:

```bash
deployment/local-lab/lab.sh kill cust-na
```

Within about ten seconds `cust-na`'s dot turns amber (suspect) and then red (dead), the membership tile
changes, a warning notice appears and the badge's dot changes colour. Start it again
(`lab.sh start cust-na`) and watch it return to alive. Call `calc_loan_amortization` a few times
(Tutorial 29, step 5): the line from `risk-eu` to the host thickens, and the calls appear under Recent
forwarded calls with their trace ids.

### 6. Remote tools

**SAJHA Net > Remote tools** (`/admin/sajhanet/tools`) is the administrator's host and tool table: every
remote tool row with net, host, state, trust, contract hash, data classes and place in the resolution
order, with filters by net, host, state and trust. Tools held under `review` trust have **Approve** and
**Withdraw**; contract conflicts are listed above the table with every offer and its hash
([Tutorial 29](TUTORIAL_29_local_test_lab.md), step 11, makes one).

### 7. SAJHA Net admin

**SAJHA Net > SAJHA Net admin** (`/admin/sajhanet`) holds the actions, per net:

- the members with their URLs and states;
- **Add a peer by address** (contact a server now, optionally keeping it as a runtime seed). On the lab
  this refuses 127.0.0.x: peer addresses given by hand may not be loopback addresses;
- **Admission**: the first-use keys, pins or CA panel;
- **Identity and access**: the user identity resolver, the key directory version, unknown-user handling
  and name matching; the blocks table and a form to add a block (level, instance, tool or
  `user@instance`, reason, minutes); remote users seen; the key directory per home with **re-sync**.

Add an inbound block on `cust-na`'s admin page against `risk-eu` with a reason, then look at `risk-eu`'s
Net overview: under Blocks it lists the block `cust-na` published naming this server, and a notice says
so. Remove it on `cust-na`.

### 8. On the Tools page and Ask

The **Tools** page marks remote tools with a net badge (net, host, data classes) and filters by **Local
and remote** / **Remote (SAJHA Net)**, net and instance. The Ask page's "Servers and tools" log names the
net and host of every remote call.

## What you learned

- The badge names this server in its net and links to the Instances page
- Instances and an instance's page show who is in the net and what each offers you, with Try it
- Your net access shows any user every remote tool, its hosts in order and whether they may use it
- The Net overview combines membership, topology, admission, notices, blocks and recent traffic; Remote
  tools and SAJHA Net admin are where administrators act

## Next

- [Tutorial 33: Proxied MCP Servers](TUTORIAL_33_proxied_mcp_servers.md)
- Each page's own help: the "About this page" panel at its foot

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
