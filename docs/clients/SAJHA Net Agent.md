# SAJHA Net Agent

The SAJHA Net agent puts any MCP server into a SAJHA Net as a full participant. It runs next to the
server (a sidecar), reaches it over stdio or Streamable HTTP, and does everything a participant must:
it holds the participant's certificate, gossips, publishes the server's tools as its catalog with net
metadata, verifies the users of forwarded calls (`api_key`, `assertion` or `token_exchange`), applies its
export policy, blocks and residency rules, and passes the calls it allows to the server. Given users and a
client listener it is also a **home**: its local MCP clients call other members' tools through it, and it
can re-export what it imports (section 6). Other members see it as an instance of kind `agent`.

It is one of the three ways to take part in a net ([SAJHA Net](../architecture/SAJHA%20Net.md#51-three-ways-to-take-part) §5.1):

| You have | Use |
|---|---|
| a SAJHA server | SAJHA Net itself (`sajhanet.*`; [Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)) |
| any MCP server you run, in any language | this agent in front of it, or the reference library inside a Python server (section 7) |
| an MCP server you cannot run beside anything (a vendor's or SaaS endpoint) | a SAJHA server sponsors it (section 8) |

The agent is part of SAJHA, which is proprietary software of Ashutosh Sinha, all rights reserved: running
it beside a server, or redistributing it, needs a separate written agreement (see the `LICENSE` file at the
root of the repository). The wire protocol is [SAJHA Net Protocol](../protocol/SAJHA%20Net%20Protocol.md); a third-party
implementation that speaks it claims conformance as target A or L (section 9).

---

## 1. What it needs

The agent is the package `sajhanet_agent/` at the root of the repository. It is built only on the SAJHA Net
protocol core (`sajha/net/`) and the reference library (`sajha/net/library.py`); it never loads the SAJHA
server, its database or its web framework (`tests/test_sajhanet_agent_boundary.py` enforces this). From a
checkout it needs Python and three libraries the server already lists in `requirements.txt`:
`cryptography`, `httpx` and `jsonschema`.

```bash
python -m sajhanet_agent --help
```

---

## 2. Run it

```bash
python -m sajhanet_agent \
  --net acme-net --instance vendor-search --vendor acme \
  --url https://agent.example.internal:8790 \
  --seed https://risk-eu.example.internal:3002 \
  --mcp-command "python vendor_server.py"
```

| Option | Meaning |
|---|---|
| `--net`, `--instance` | The net to join and this participant's instance name in it (protocol §5.1, §5.2). |
| `--vendor` | Required. The organisation that owns and answers for the server's tools (`acme`), in the member record ([SAJHA Net](../architecture/SAJHA%20Net.md) §5.6): a lowercase letter, then lowercase letters, digits and `_`, at most 24 characters. |
| `--external` | Refused (exit code 2). An agent-fronted server is a member of the net, and an external server never is: to offer a server's tools under its vendor's prefix without making it a member, define it on an internal SAJHA instance as a proxied MCP server marked external (an entry of `config/mcp_servers.json`, or `sajhanet.external_servers`), pointing at the server or at the MCP server behind this agent ([SAJHA Net](../architecture/SAJHA%20Net.md) §5.6). |
| `--rename local=published` | Offer one tool under a name of your choosing (repeatable); it falls under one name, one contract like any name. A tool whose qualified name would exceed 128 characters is not offered; the status lists it under `refused_tools`. |
| `--url` | The base URL peers reach the agent on. Its host must be one the certificate names. |
| `--listen` | `host:port` to listen on; default all interfaces and the port of `--url`. |
| `--seed` | A member to join through (repeatable). |
| `--founder` | Start the net alone when no seed answers. |
| `--mcp-command` / `--mcp-url` | The server: a command run over stdio, or a Streamable HTTP endpoint (`--mcp-header "Name: value"` adds a header, for example the server's own credential). |
| `--admission` | `open` (default), `builtin_ca` or `manual`; section 3. With `builtin_ca`, `--ca-url` (the CA participant's base URL) and `--token` (the enrollment token, spent on first start); with `manual`, `--pin` (a peer certificate thumbprint to trust, repeatable). |
| `--data-dir` | Where the key, certificate, CA certificate, first-use keys and saved peer list live (default `data/sajhanet-agent`). The key never leaves it. |
| `--export-tools`, `--export-peers`, `--export-roles` | The export policy (section 4). |
| `--service-calls` | Also serve calls that carry no user. |
| `--no-key-verification` | Keep no key directory and accept no forwarded keys (service calls only). |
| `--region`, `--label k=v` | Placement shown to other members and used by their residency rules. |
| `--tls-cert`, `--tls-key` | Serve HTTPS. |
| `--behind-tls-proxy` | A TLS proxy terminates HTTPS in front of the agent (requests count as HTTPS). |
| `--allow-plain-http` | Lab use only: no HTTPS required for enrollment, peers or forwarded keys. |
| `--call-timeout`, `--catalog-refresh` | Seconds for one call to the server, and between `tools/list` on it (default 60 each). |
| `--config` | The configuration file (JSON, section 6): users and their keys, identity resolvers, import rules, blocks, residency rules and re-export rules. Re-read when it changes. |
| `--client-listen` | `host:port` on which to serve MCP to local clients (`/mcp`, Streamable HTTP); makes the agent a home (section 6.2). Keep it on loopback or a private interface. |
| `--log-level` | Default `INFO`. |

The agent answers `/sajhanet/v1/...` (membership, catalog, key directory), the signed MCP endpoint at
`/mcp` (forwarded `tools/call` and `tools/list`, `server/discover`, `initialize`, `ping`), and a
health check for orchestrators (a `GET` of `healthz` at the root of the agent's address, answering
`{ok, net, instance, joined}`; the agent's own path, not a SAJHA route). An unsigned `server/discover` or `initialize` gets only the reduced extension object
(protocol §6.1); every other unsigned MCP request is refused: the agent is a door into the net, not a
second public endpoint for the server. On SIGTERM it leaves the net (a signed leave) and stops.

A server whose tool list changes may send `notifications/tools/list_changed`; the agent then pulls
`tools/list` again and its new catalog digest reaches the other members by gossip.

---

## 3. Identity

| `--admission` | How the agent gets its certificate | What peers check |
|---|---|---|
| `open` (default, as SAJHA ships) | A self-signed certificate, made at first start and kept in `--data-dir`. | First use: the key first seen for the name is remembered, and a later server claiming the name with another key is refused. |
| `builtin_ca` | Enrollment with the net's CA participant: `--ca-url` and a one-time `--token` that its administrator creates (`sajha net ca enroll --net <net> --instance <name>`). Renewed at the CA when a third of its validity remains. | The chain to the net's CA and its revocation list. |
| `manual` | A self-signed certificate; peers pin its thumbprint (`sajha net pin`). `--pin` pins theirs here. | Pinned thumbprints. |

The token is spent on the first start; later starts use the saved certificate. All members of a net use
the same admission mode. Open mode trusts whoever first claims a name and has no revocation
([SAJHA Net](../architecture/SAJHA%20Net.md#64-admission-modes) §6.4); use `builtin_ca` before a net spans
machines you do not control.

---

## 4. Who may call what

A forwarded call is checked in the order of protocol §15.4: signature, version, blocks on the sender, hops
and loops, the user's identity, the block on the user, the block on the tool, export, then the call and
the residency of its result. The agent's part:

- **Identity.** With key verification on (the default) the agent keeps a copy of the net key directory,
  pulled from each member when its key digest changes, and accepts the resolvers of the configuration
  file's `identity` list (default `api_key`): a forwarded key, checked in the directory (unknown, disabled,
  expired, revoked, or not from the sending home are refused with the protocol's reasons); a user
  assertion signed by the user's home (`assertion`: schema, net, issuer, signature, audience, time window,
  one use, trace id and key record, protocol §15.5); or a token it issued at its own
  `/sajhanet/v1/token` in exchange for such an assertion (`token_exchange`, §15.9; feature
  `token_exchange`, tokens live `token_ttl_seconds`). An assertion is also accepted in the re-export cases
  of §16 even where `assertion` is not listed. The user is the key's owner at their home, with their roles
  there; the agent has no accounts of its own and maps nobody.
- **Export policy.** `--export-tools` (globs of the server's tool names, or of their published names),
  `--export-peers` (globs of instance names) and `--export-roles` (the user's roles at home; default any).
  The key's own tool access is a ceiling, as on every host. A tool the policy does not offer to a peer is
  neither in that peer's catalog nor callable by it.
- **Blocks** (feature `blocks`; the file's `blocks`). `instance` and `inbound` refuse a sender (and stop
  offering it anything), `user` refuses calls on behalf of `<login>@<home>`, `tool` with direction
  `inbound` refuses one of the server's tools. The agent publishes its blocks document at
  `/sajhanet/v1/blocks` like any member, its version growing with each change.
- **Residency** (feature `residency`). The server's tools' schema marks (`x-sajha-data-class`) and the
  file's `residency.tools` overlay give their data classes, shown in the catalog's `data_classes`; the
  file's residency rules decide whether a result may leave for the calling home (refused
  `residency_result`, executed, or redacted field by field).
- **Calls without a user** (another participant's service identity) are refused unless `--service-calls`.

The server behind the agent still applies whatever authorization it has of its own.

---

## 5. What a call looks like at the server

The agent sends the server an ordinary `tools/call` with the arguments it received. If the server cannot be
reached at all, the caller gets a refusal with `executed: false` (so a home may fall back to another host);
once the request may have reached the server, an error is returned as the tool's result, never as a
refusal. Results go back signed, with `_meta["io.sajha/net"].instance` set.

---

## 6. The configuration file, and the agent as a home

### 6.1 The configuration file

`--config` names a JSON file holding what does not fit a flag. The agent reads it at start and again
whenever it changes (checked every protocol period); an edit that does not parse is not applied, the last
good configuration stays and the status says why. Every section is optional.

```json
{
  "identity": ["assertion", "api_key"],
  "users": [
    {"user_name": "alice", "display_name": "Alice", "roles": ["analyst"],
     "keys": [{"id": "alice-1", "key": "<the raw key>", "tool_access_mode": "all"}]}
  ],
  "import": [{"tools": ["*"], "instances": ["*"]}],
  "blocks": [{"id": "b1", "level": "outbound", "target_instance": "risk-us", "reason": "under review"}],
  "residency": {
    "default_effect": "allow",
    "tools": {"lookup_person": {"arguments": {"email": "eu-personal"}}},
    "rules": [{"id": "eu-stays", "match": {"data_classes": ["eu-personal"], "flow": "arguments",
               "destination": {"labels.jurisdiction": {"ne": "EU"}}}, "effect": "deny"}]
  },
  "reexport": {"enabled": true, "rules": [{"tools": ["ledger"], "from_instances": ["ledger-c"], "to_instances": ["desk-d"]}]},
  "max_hops": 2
}
```

| Key | Meaning |
|---|---|
| `identity` | The resolvers this agent accepts as a host and sends as a home, in order of preference: `api_key`, `assertion`, `token_exchange` (default `["api_key"]`). As a home it sends the first one the host lists. |
| `users` | The agent's own users, each with `user_name`, `display_name`, `roles` and `keys`. A key has an `id` (at most 64 characters), the raw `key` or its `sha256`, and optionally `name`, `enabled`, `expires_at`, `tool_access_mode` (`all`, `allowlist`, `denylist`, `regex`) and `tool_access_list`. The agent publishes a key record for each in the net key directory (only the hash crosses), so hosts can verify its users; the records are kept in `own_keys.json` in `--data-dir` so their versions keep growing across restarts. A key removed from the file becomes a tombstone. |
| `anonymous_calls` | `true`: a local client without a key may call; its calls carry no user, so a host serves them only if it accepts service calls. Default `false`. |
| `import` | Which remote tools the agent's local clients may use: rules `{tools, instances, for_roles}` (globs; `for_roles` the local user's roles). Nothing is imported unless a rule allows it; a rule with an empty `instances` imports its tools from nobody. Without the section every tool is imported. |
| `blocks` | Blocks of [SAJHA Net](../architecture/SAJHA%20Net.md#114-blocking) §11.4: `{id, level, target_instance, tool, direction, user, reason, expires_at}`, `level` one of `instance`, `inbound`, `outbound`, `tool`, `user`. `outbound`, `instance` and `tool` with direction `outbound` (`tool` a qualified-name glob) hide a member's tools from the local clients and are never called. |
| `residency` | `default_effect` (`allow`, or `deny`: classified data needs an allow rule), `tools` (a tool-name glob to the data classes of its `arguments` and `results`, by field path or for the whole value) and `rules` of the shape of SAJHA's residency rules ([Policy and Audit](../architecture/Policy%20and%20Audit.md#35-residency-rules-sajha-net) §3.5): `match` (`data_classes`, `flow`: `arguments` or `results`, `destination`: conditions on `net`, `instance`, `region`, `labels.<key>`, `here`, plus `differs_from_here`), `effect` (`allow`, `deny`, `require_approval`), `redact.data_classes`, `reason`. Deny overrides. |
| `reexport` | `enabled` and `rules` `{tools, from_instances, to_instances, for_roles}` (section 6.3). |
| `max_hops`, `max_call_chain` | The hop limit (default 1, or 2 with re-export on) and the hops-plus-nesting budget (default 8) of protocol §16; an agent that is the origin of a re-exported tool needs `max_hops: 2`. |
| `token_ttl_seconds`, `assertion_ttl_seconds` | Lifetimes of the tokens it issues (default 300) and the assertions it signs (default 30, at most 60). |
| `bare_aliases` | `on` (default): local clients also see a remote tool under its plain name while no own tool has it; `off`: qualified names only. |

### 6.2 The agent as a home

With `--client-listen` the agent opens a second listener for its own MCP clients: Streamable HTTP at
`/mcp`, JSON answers, `initialize`, `ping`, `tools/list` and `tools/call`. A client presents one of the
file's keys (`Authorization: Bearer <key>` or `X-API-Key`); a client without one is refused (HTTP 401)
unless `anonymous_calls` is on.

- `tools/list` shows the server's own tools under their own names, and every remote tool the import rules,
  blocks and residency rules allow as a proxy under its qualified name `<net>__<host prefix>__<tool>` and,
  while no own tool has it, under its plain name ([SAJHA Net](../architecture/SAJHA%20Net.md#82-names-and-resolution)
  §8.2), with `_meta["io.sajha/net"]` naming its host. The key's tool access is a ceiling on both.
- A call of an own tool goes to the server. Any other call is resolved and forwarded as SAJHA does:
  a qualified name goes exactly there, a plain name follows the resolution order and falls back between
  hosts (§9.1 there); the call is signed, carries the hop headers and the user as the host accepts it
  (above), and the result comes back verified. A refusal reaches the client as a result with
  `isError: true` and `_meta["io.sajha/net"].refusal`.
- **Residency at the home.** Before arguments leave, the rules decide with the host as destination: the
  call goes, is refused `residency_arguments` (side home, not executed), or goes with the fields of the
  named classes replaced by `[REDACTED:<class>]`. A rule with `require_approval` refuses too: the agent
  has no approval surface (no administrator signs in to it), so the refusal says the call needs a
  person's approval that this agent cannot ask for, and to call the tool from a SAJHA server, where an
  administrator can approve it, or change the rule. As a result arrives, the rules decide again with
  this agent as the destination (`here`).
- The agent pulls other members' catalogs only while it is a home or re-exports; otherwise it imports
  nothing, as before.

### 6.3 Re-export

With `reexport.enabled` and a matching rule the agent offers an imported tool to the members its
`to_instances` name, as its own entry with `origin` set to the tool's host (feature `reexport`, protocol
§16); a rule with an empty `to_instances` re-exports to nobody. A tool is never offered back to its host
or origin. A call to it must carry a user assertion for the origin; the agent checks its re-export rule
for that caller and relays the call to the origin with the assertion unchanged, the hop count and visited
list continued, and never with a key. The origin must accept hop 2 (`max_hops: 2` there).

### 6.4 Limits

The agent does not list `streaming`, `progress`, `cancellation`, `mrtr`, `tasks` or `visibility`: homes send
it plain JSON calls and hold any task themselves, and as a home it asks hosts for plain JSON answers. Its
local clients reach it over Streamable HTTP only (no stdio), and it is in one net only, so it is never a
bridge between nets. A residency rule that needs approval refuses (section 6.2). What SAJHA Net as a
whole does not have yet is in [SAJHA Net](../architecture/SAJHA%20Net.md#55-what-is-built) §5.5.

---

## 7. The reference library

`sajha.net.library` is the agent without the MCP client: a complete participant for a Python server that
wants to join a net itself.

```python
from sajha.net.library import NetParticipant, StaticTools

def execute(ctx, arguments):            # ctx: net, peer, user, tool, trace id, hop, visited
    return {'content': [{'type': 'text', 'text': f'hello {arguments.get("name")}'}]}

p = NetParticipant.build(net='acme-net', instance='greeter', base_url='https://greeter.example:8443',
                         seeds=['https://risk-eu.example:3002'], data_dir='data/greeter',
                         source=StaticTools([{'name': 'greet', 'inputSchema': {'type': 'object'}}]),
                         execute=execute).start()
p.run_in_background()                   # the gossip agent
# serve every request to /sajhanet/... and /mcp with:
#   response = p.handle(method, path, query, headers, body, secure=True)
```

`NetParticipant.build` takes the same identity choices as the agent (`admission`, `ca_url`, `token`,
`pins`), an export policy (`rules`, by default `ExportPolicy`) and `verify_keys`. A raised
`HostRefusal('unavailable')` in `execute` refuses a call that did not run.

---

## 8. Sponsoring instead

A server that cannot have an agent beside it is sponsored by a SAJHA server: the SAJHA server connects to
it as a federation upstream and represents it in the net under an instance name of its own (kind
`sponsored`, its member record naming the sponsor), with the sponsor's export rules, access, policy,
residency and audit on every call. Configure `sajhanet.sponsored`
([Configuration Reference](../getting-started/Configuration%20Reference.md#sajha-net)) or use the admin
API (`/api/sajhanet/sponsored`, [API Reference](../protocol/API%20Reference.md#424-sajha-net-sajhanet_routespy)).
How sponsoring works: [SAJHA Net](../architecture/SAJHA%20Net.md#57-sponsored-servers) §5.7.

---

## 9. Conformance

The conformance suite of protocol §20 runs against any participant:

```bash
# a SAJHA instance or an agent; the runner enrolls itself with a token in a builtin_ca net
python -m sajha.net.conformance --target https://agent.example.internal:8790 --net acme-net \
    --ca-url https://risk-eu.example.internal:3002 --token <token>
# a sponsored participant shares its sponsor's URL: name it
python -m sajha.net.conformance --target https://risk-eu.example.internal:3002 --net acme-net --instance vendor-search
# the library cases, against this checkout's protocol core
python -m sajha.net.conformance --target library
```

Every id of §20 is reported `pass`, `fail` or `skip`: skipped when the case is not for the target (its
targets, or a feature the target does not advertise), or when it needs the target's insides (clocks, CA
administration, several failing members), in which case the report names the file of SAJHA's own suite that
covers it. Without `--ca-url`, the runner uses a self-signed identity, which only an open-admission net
accepts (and remembers by name: give `--name` and `--identity-dir` to reuse one). `--api-key` adds CALL-01
with a real user's key; `--json` prints the report as data; the exit status is 1 when a case fails. SAJHA's
own suite runs it against a SAJHA instance, an agent and a sponsored server in one net
(`tests/net/test_net_mixed_conformance.py`). The agent's cases that need its insides (CALL-07, CALL-13,
CALL-14 and CALL-15 as host and as home, blocks, residency and re-export) are in
`sajhanet_agent/tests/test_home.py`, and an agent home next to a SAJHA instance in
`tests/net/test_net_agent_home.py`.
