# SAJHA Net Protocol

> **Status: specification of a design that is not built yet.** This document specifies the wire
> protocol of [SAJHA Net](../architecture/SAJHA%20Net.md): the `io.sajha/net` MCP extension that
> participants in a net speak to each other. It is written so that someone outside SAJHA can build a
> participant (a SAJHA Net agent, a library, another server) from it alone. The design note owns the
> rationale, the console, storage and configuration; this document owns the bytes on the wire. Where
> the two disagree, report it: the design is not automatically right, and neither is this.

This document defines **SAJHA Net protocol version 1**.

---

## Contents

1. [Scope](#1-scope)
2. [Conventions](#2-conventions)
3. [Roles and conformance targets](#3-roles-and-conformance-targets)
4. [Protocol version and versioning](#4-protocol-version-and-versioning)
5. [Names](#5-names)
6. [Capability negotiation](#6-capability-negotiation)
7. [Transport](#7-transport)
8. [Certificates and signatures](#8-certificates-and-signatures)
9. [Membership](#9-membership)
10. [Catalog exchange](#10-catalog-exchange)
11. [Net key directory](#11-net-key-directory)
12. [Block publication](#12-block-publication)
13. [Revocation list](#13-revocation-list)
14. [Certificate enrollment and renewal](#14-certificate-enrollment-and-renewal)
15. [Tool-call forwarding](#15-tool-call-forwarding)
16. [Hops and loops](#16-hops-and-loops)
17. [Error model](#17-error-model)
18. [Limits](#18-limits)
19. [Security considerations](#19-security-considerations)
20. [Conformance](#20-conformance)
21. [Examples](#21-examples)
22. [Decisions made in this spec](#22-decisions-made-in-this-spec)
23. [References](#23-references)

---

## 1. Scope

This specification defines:

- how a participant advertises and negotiates the extension on both MCP eras;
- the HTTP endpoints under `/sajhanet/v1/` on a participant's normal HTTP port, with their request
  and response schemas: gossip, membership sync and leave, catalog, key directory, blocks,
  revocation list, certificate enrollment and renewal;
- how every request and response between participants is signed (RFC 9421), digested (RFC 9530)
  and checked, and how stored records are signed (RFC 8785 canonical JSON);
- how a tool call is forwarded to a host participant over its MCP endpoint, with the user's
  identity, trace context and hop information;
- names, merge rules, error codes, limits and a conformance test list.

It does **not** define: how a participant decides what to export or import (its rules are its own;
only their outcomes appear on the wire), its user interface, storage, configuration keys or
metrics. For those, see the [design](../architecture/SAJHA%20Net.md) (configuration in §19, storage
in §20).

## 2. Conventions

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**,
**SHOULD NOT**, **RECOMMENDED**, **NOT RECOMMENDED**, **MAY** and **OPTIONAL** in this document are to
be interpreted as described in BCP 14 (RFC 2119, RFC 8174) when, and only when, they appear in all
capitals, as shown here.

- **JSON.** Every body is UTF-8 JSON (RFC 8259) that also satisfies I-JSON (RFC 7493): no duplicate
  member names, integers within ±(2^53−1). Receivers MUST ignore members they do not understand,
  unless this document says otherwise; signatures still cover them (§8.10).
- **Field names** in extension objects are `snake_case`, matching the `_meta["io.sajha/net"]` object
  of the design (§8.3 there). MCP's own fields keep their MCP spelling.
- **Times** are RFC 3339 strings in UTC with a `Z` suffix (`2026-10-07T12:00:00Z`), except the RFC 9421
  `created` parameter, which is an integer of seconds since the Unix epoch, and the incarnation
  (§9.3), which is milliseconds since the Unix epoch.
- **Encodings.** `base64` is RFC 4648 §4 with padding; `base64url` is RFC 4648 §5 **without** padding.
  Structured header fields follow RFC 8941; a byte sequence there is `:base64:`.
- **Schemas** are JSON Schema 2020-12. Shared definitions are in [§7.6](#76-shared-schema-definitions)
  with `$id` `urn:sajha:net:v1`; endpoint schemas refer to them as `urn:sajha:net:v1#/$defs/<name>`.
- Header field names are case-insensitive; this document writes them in `Title-Case` and uses
  lowercase inside signature bases, as RFC 9421 requires.
- Terms (net, instance, home and host instance, proxy tool, export and import rules, data class,
  hop, gossip, incarnation, net key directory, block, seed) have the meanings in the design's
  [vocabulary](../architecture/SAJHA%20Net.md#3-vocabulary). This document says **participant** for
  any member of a net and **instance** where the design does; on the wire they are the same thing.

## 3. Roles and conformance targets

| Role | Meaning |
|---|---|
| **Participant** | Anything that holds a net certificate and speaks this protocol: a SAJHA instance, a server with the reference library built in, or the SAJHA Net agent in front of an MCP server. A *sponsored* MCP server is not a participant; its sponsor is. |
| **Sender / receiver** | The two ends of one HTTP exchange between participants. |
| **Home / host** | For a forwarded tool call, the participant that received the caller's request, and the participant that owns the tool. |
| **CA participant** | The one participant that runs the net's certificate authority and serves the endpoints of §14 (feature `ca`). |

Conformance targets, named in [§20](#20-conformance): **S** (a SAJHA instance), **A** (the SAJHA Net
agent), **L** (the reference library). A third-party implementation claims conformance as an A or L
target. Every requirement applies to every target unless it names one, or depends on a feature the
target does not advertise.

## 4. Protocol version and versioning

- The protocol version is a positive integer. This document defines **1**.
- A participant advertises every version it speaks (`protocol_versions`, §6.1) and its member record
  carries the same list (§9.1). Two participants use the **highest version both list**. A participant
  MUST refuse a peer whose highest common version is below its own configured minimum (in SAJHA,
  `sajhanet.min_protocol_version`), with `unsupported_version` (§17).
- Every request and response between participants carries `Sajha-Net-Version: <n>`, the version in use
  for that exchange, covered by the signature. A receiver that does not speak `<n>` MUST answer
  `400 unsupported_version` (or JSON-RPC `-32017` on the MCP endpoint) listing the versions it speaks.
- **Compatible changes** keep the version: new optional members in any object, new endpoints, new
  feature flags (§6.2), new `reason` values. Receivers MUST ignore unknown members and feature flags,
  and MUST treat an unknown `reason` as its JSON-RPC code's general meaning.
- **Incompatible changes** (a removed or reinterpreted member, a changed signature base, a new
  mandatory check) take a new version, served under a new path prefix (`/sajhanet/v2/`) so that one
  participant can serve both during a migration.
- The protocol version is independent of MCP protocol versions and of any implementation's release
  version.

## 5. Names

### 5.1 Net names

A net name MUST match `^[a-z][a-z0-9-]{0,62}$` (for example `acme-net`). It appears in every
certificate (§8.1) and member record.

### 5.2 Instance names

An **instance name** identifies a participant in its net and is either configured or an address.

- A **configured name** MUST match `^[a-z][a-z0-9-]{0,30}[a-z0-9]$`: lowercase letters, digits and
  single hyphens, starting with a letter, ending with a letter or digit, 2 to 32 characters, and MUST
  NOT contain `--`. It never contains `_`, `.` or `:`.
- An **address name** is used when none is configured: `<ipv4>:<port>` (`10.20.4.17:3002`) or
  `[<ipv6>]:<port>` (`[2001:db8::7]:3002`). The address MUST be one other participants can reach. It
  MUST NOT be unspecified (`0.0.0.0`, `::`), loopback (`127.0.0.0/8`, `::1`), `localhost` or
  link-local (`169.254.0.0/16`, `fe80::/10`), and MUST NOT carry an IPv6 zone. IPv6 addresses are
  written in their RFC 5952 canonical text form in the name.
- Instance names are compared byte for byte. Two participants in one net MUST NOT have the same name;
  the certificate (§8.1) is what makes a name unforgeable.
- **Name ownership.** A name belongs to the key that first holds it in the net: the public key of the
  certificate naming it (its thumbprint, §8.1). The name stays reserved for that key, whatever the
  holder's membership state (`alive`, `suspect`, `dead`, `left`), until the holder's certificate is
  revoked (§13). A restart with the same key, or a renewed certificate for the same key, is the same
  holder, not a conflict.
- **Collisions are refused, loudly.** A participant that receives a join, sync, ping or signed request
  whose sender name is held by a different key whose certificate is not revoked MUST refuse it with
  `409 name_conflict` (§7.3), whose problem body names the current holder (`holder_url`,
  `holder_thumbprint`, `holder_state`). The refused participant MUST NOT join the net: it MUST log the
  refusal at error level, surface it to its operators (SAJHA: a red banner on every console page and
  the `sajha_net_name_conflict` metric), MUST stop retrying the join until its configuration or
  certificate changes, and MAY keep serving its own tools locally. Members MUST NOT add the newcomer to
  their membership list or relay gossip about it, and SHOULD raise their own alert naming both
  claimants.
- **Prevention at the CA.** The CA participant MUST refuse to create an enrollment token (§14.1) for a
  name held by a key whose certificate is not revoked, telling the administrator who holds it; a
  replacement for a lost key requires revoking the old certificate first.

### 5.3 Safe prefix and qualified tool names

A tool's **qualified name** is `<safe prefix>__<host tool name>`. The separator is exactly two
underscores.

| Instance name | Safe prefix | Rule |
|---|---|---|
| configured (`risk-eu`) | `risk-eu` | the name itself |
| IPv4 address (`10.20.4.17:3002`) | `10_20_4_17_3002` | replace every `.` and `:` with `_` |
| IPv6 address (`[2001:db8::7]:3002`) | `2001_0db8_0000_0000_0000_0000_0000_0007_3002` | drop the brackets; write all eight groups as four lowercase hex digits, without `::` shortening (an IPv4-mapped address is written as two final hex groups too); join groups with `_`; append `_<port>` |

- A safe prefix never contains `__`, so a qualified name splits at its **first** `__`: the left part
  is the prefix, the rest is the host's own tool name, which MAY itself contain `__`.
- Participants MUST compute the prefix exactly as above and MUST NOT alter it further, so the same
  tool has the same qualified name everywhere.
- A qualified name longer than 64 characters SHOULD be reported to an administrator, because some LLM
  providers cap tool names at 64; it remains valid on the wire. MCP itself bounds tool names to
  128 characters, and a participant MUST NOT offer a qualified name longer than that.

### 5.4 Net users

A net user is written `<user name>@<instance name>` (`alice@risk-eu`, `alice@10.20.4.17:3002`). It
names a user **at** an instance; it is never assumed to be the same person as a user of the same name
elsewhere (design §11.3).

## 6. Capability negotiation

The extension id is **`io.sajha/net`**.

### 6.1 Server advertisement

A participant with SAJHA Net enabled advertises the extension object below in both MCP eras:

- **2026-07-28:** in the `server/discover` result, at `capabilities.extensions["io.sajha/net"]`,
  alongside the other extensions (SAJHA builds this map in `sajha/core/mcp_modern.py`, where the
  tasks and MCP Apps extensions are added).
- **2025-11-25:** in the `initialize` result, at `capabilities.experimental["io.sajha/net"]`. That
  era's `ServerCapabilities` has no `extensions` member, so the object goes where SAJHA already puts
  its era-specific settings (`experimental`).

A receiver of either result MUST look in both places.

```json
{
  "capabilities": {
    "tools": { "listChanged": true },
    "extensions": {
      "io.modelcontextprotocol/tasks": {},
      "io.sajha/net": {
        "protocol_versions": [1],
        "net": "acme-net",
        "instance": "cust-na",
        "kind": "sajha",
        "endpoint": "/sajhanet/v1/",
        "features": ["gossip", "catalog", "visibility", "key_directory", "key_verification",
                     "blocks", "residency", "llm_tools", "progress", "cancellation", "mrtr", "tasks"],
        "user_identity": ["api_key"],
        "signature_algorithms": ["ed25519", "ecdsa-p256-sha256"]
      }
    }
  }
}
```

The 2025-11-25 form is the same object under `"experimental": { "io.sajha/net": { ... } }`.

To an MCP request that is not signed by a participant (§8), a participant MAY reduce the object to
`{"protocol_versions": [...], "endpoint": "..."}`, so that an anonymous client does not learn the net
name or the feature list.

Schema: `urn:sajha:net:v1#/$defs/extension`.

### 6.2 Feature flags

A participant lists in `features` what it supports. Peers use a feature only when **both** list it
(for features that need both ends) or when the side that must act lists it.

| Flag | Meaning when listed |
|---|---|
| `gossip` | Serves §9.5 to §9.8 (ping, ping-req, sync, leave). Without it, the participant's membership comes from a static list or its sponsor. |
| `catalog` | Serves the catalog endpoint (§10.2) and the signed `tools/list` equivalent (§10.4). REQUIRED for any participant that exports tools. |
| `visibility` | Serves per-key visibility queries (§10.5). |
| `key_directory` | Issues API keys and serves its key records (§11). |
| `key_verification` | Verifies forwarded API keys against the net key directory (§15.3). REQUIRED to accept `api_key` identity. |
| `blocks` | Publishes its blocks (§12). |
| `residency` | Honours `x-sajha-data-class` on arguments and results and the residency refusals of §17. |
| `llm_tools` | Exports LLM tools (tools whose work is done by a model) and marks them `llm_tool: true`. |
| `progress` | Relays progress notifications of forwarded calls. |
| `cancellation` | Relays cancellation of forwarded calls. |
| `mrtr` | Relays multi-round input requests (`input_required` results) of forwarded calls. |
| `tasks` | Accepts task-augmented forwarded calls (the MCP tasks extension) for the resolved user. |
| `reexport` | May offer, and accepts calls to, tools it imported from other participants (§16). |
| `ca` | Is the CA participant and serves §14. |

`user_identity` lists the identity resolvers the participant accepts as a host and can produce as a
home: `api_key` (§15.3), `assertion` (§15.5), `token_exchange` (reserved; RFC 8693, not specified in
version 1), `none` (service identity only). Version 1 participants MUST support `api_key` unless they
list only `none`.

### 6.3 Client declaration

When a participant calls another's MCP endpoint (catalog through `tools/list`, or a forwarded tool
call), it SHOULD declare the extension as a client:

- **2026-07-28:** `params._meta["io.modelcontextprotocol/clientCapabilities"].extensions["io.sajha/net"] = {"protocol_version": 1}`.
- **2025-11-25:** in `initialize`, `params.capabilities.experimental["io.sajha/net"] = {"protocol_version": 1}`.

Whether a request is a net request is decided by its signature headers (§8), not by this
declaration. A host MUST NOT refuse a correctly signed request only because the declaration is
absent.

### 6.4 Era for forwarded calls

A home MUST forward on 2026-07-28 when the host lists it in `supportedVersions`, and otherwise on
2025-11-25 with one MCP session per (home, host) pair. A 2025-11-25 session created by a signed
request from participant X MUST only be used by signed requests from X (`Mcp-Session-Id` is not an
identity; every request is signed and its user resolved individually).

## 7. Transport

### 7.1 Where the endpoints live

Every participant has a **base URL** (`url` in its member record, §9.1), an HTTPS origin optionally
followed by a path prefix with no trailing slash. All net endpoints are `<url>/sajhanet/v1/...` and the
MCP endpoint is `<url><mcp_path>` (default `/mcp`). They share the participant's normal HTTP port: no
second port, no UDP.

### 7.2 Endpoints

| Method and path | Purpose | Signed request | Section |
|---|---|---|---|
| `POST /sajhanet/v1/gossip/ping` | Failure detection, piggybacked updates | yes | §9.5 |
| `POST /sajhanet/v1/gossip/ping-req` | Indirect probe through a third participant | yes | §9.5 |
| `POST /sajhanet/v1/membership/sync` | Full push-pull of the membership list; join through a seed | yes | §9.7 |
| `POST /sajhanet/v1/membership/leave` | Announce a clean departure | yes | §9.8 |
| `POST /sajhanet/v1/catalog` | Pull the tools this participant exports to the caller | yes | §10.2 |
| `POST /sajhanet/v1/catalog/visibility` | Which exported tools given keys' users may call | yes | §10.5 |
| `POST /sajhanet/v1/keys` | Key-directory delta pull | yes | §11.3 |
| `POST /sajhanet/v1/keys/digest` | Key-directory digest for anti-entropy | yes | §11.4 |
| `POST /sajhanet/v1/blocks` | Pull the blocks this participant publishes | yes | §12 |
| `GET /sajhanet/v1/revocations` | Fetch the CA-signed revocation list | yes | §13 |
| `POST /sajhanet/v1/ca/enroll` | Certificate request with an enrollment token | **no** (token) | §14.1 |
| `POST /sajhanet/v1/ca/renew` | Certificate renewal | yes | §14.2 |
| `POST <mcp_path>` | Forwarded MCP requests (`tools/call`, `tools/list`, ...) | yes | §15 |

Every response from every row is signed (§8.8), including error responses.

### 7.3 Common rules

- Participants MUST use HTTPS between each other. A participant MAY allow plain HTTP for a lab, but
  then MUST NOT send or accept a forwarded API key (§15.3) and SHOULD say so loudly to its operators.
- Request and response bodies are `application/json`; error bodies are `application/problem+json`
  (RFC 9457). Every POST has a body (at least `{}`); the GET has none.
- When SAJHA Net is disabled, every `/sajhanet/` path MUST answer `404` with no body detail, as if it
  did not exist. A participant that does not list a feature MUST answer `404` on that feature's paths.
- Net endpoints are not for browsers. A request without a valid signature (except §14.1) MUST be
  refused; responses MUST NOT carry CORS headers or set cookies; a request with
  `Sec-Fetch-Mode: navigate` MUST be refused with `404`.
- Proxies between participants MUST pass the method, path, query, body and every covered header
  (§8.5) unchanged. TLS may end at a proxy: identity is in the signature, not in the TLS session.
- A receiver SHOULD rate-limit per sender (by certificate) and answer `429` with `Retry-After`.

### 7.4 HTTP status codes on `/sajhanet/`

| Status | `reason` values | When |
|---|---|---|
| 200 | | Success. |
| 400 | `invalid_request`, `unsupported_version`, `unknown_member` | Body fails its schema; version not spoken; a ping-req target that is not a known member. |
| 401 | `signature_missing`, `signature_invalid`, `signature_incomplete`, `signature_expired`, `replay`, `digest_mismatch`, `certificate_invalid`, `from_mismatch` | The request could not be authenticated (§8.7). |
| 403 | `certificate_revoked`, `instance_revoked`, `net_mismatch`, `blocked`, `enrollment_refused`, `not_home` | Authenticated but not allowed. |
| 404 | | Net disabled, unknown path, or feature not offered. |
| 405 | | Wrong method. |
| 409 | `name_conflict` | The sender's name is the receiver's own name, or is held in the net by a different key whose certificate is not revoked (§5.2). The body carries `holder_url`, `holder_thumbprint` and `holder_state`. |
| 413 | `too_large` | Body over the limits of §18. |
| 415 | | Not `application/json`. |
| 421 | `recipient_mismatch` | `Sajha-Net-To` is not the receiver's instance name. |
| 429 | `rate_limited` | Too many requests; `Retry-After` given. |
| 503 | `unavailable` | Temporarily unable (for example the CA key is not loaded); `Retry-After` given. |

### 7.5 Problem body

```json
{
  "type": "urn:sajha:net:error:signature_expired",
  "title": "Signature too old",
  "status": 401,
  "reason": "signature_expired",
  "detail": "created is 41 s before receipt; the maximum age is 30 s",
  "supported_versions": [1]
}
```

`type` is `urn:sajha:net:error:<reason>`. `detail` MUST be safe to show to an operator of the other
participant and MUST NOT contain secrets. `supported_versions` is present only for
`unsupported_version`. Schema: `urn:sajha:net:v1#/$defs/problem`.

### 7.6 Shared schema definitions

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sajha:net:v1",
  "$defs": {
    "net_name":      { "type": "string", "pattern": "^[a-z][a-z0-9-]{0,62}$" },
    "instance_name": { "type": "string", "maxLength": 47,
      "anyOf": [
        { "pattern": "^[a-z][a-z0-9-]{0,30}[a-z0-9]$", "not": { "pattern": "--" } },
        { "pattern": "^[0-9]{1,3}(\\.[0-9]{1,3}){3}:[0-9]{1,5}$" },
        { "pattern": "^\\[[0-9a-f:.]+\\]:[0-9]{1,5}$" } ] },
    "timestamp":     { "type": "string", "format": "date-time", "pattern": "Z$" },
    "b64":           { "type": "string", "contentEncoding": "base64" },
    "b64url":        { "type": "string", "pattern": "^[A-Za-z0-9_-]+$" },
    "version":       { "type": "integer", "minimum": 0, "maximum": 9007199254740991 },
    "cert_chain":    { "type": "array", "minItems": 1, "maxItems": 4,
                       "items": { "$ref": "#/$defs/b64" },
                       "description": "DER X.509 certificates, leaf first, without the root" },
    "signature": {
      "type": "object", "required": ["alg", "keyid", "sig"], "additionalProperties": false,
      "properties": {
        "alg":   { "enum": ["ed25519", "ecdsa-p256-sha256"] },
        "keyid": { "$ref": "#/$defs/b64url" },
        "sig":   { "$ref": "#/$defs/b64url" } } },
    "extension": {
      "type": "object", "required": ["protocol_versions", "endpoint"],
      "properties": {
        "protocol_versions": { "type": "array", "minItems": 1, "items": { "type": "integer", "minimum": 1 } },
        "net":       { "$ref": "#/$defs/net_name" },
        "instance":  { "$ref": "#/$defs/instance_name" },
        "kind":      { "enum": ["sajha", "agent", "sponsored"] },
        "endpoint":  { "type": "string", "pattern": "^/.*/$" },
        "features":  { "type": "array", "items": { "type": "string" }, "uniqueItems": true },
        "user_identity": { "type": "array", "items": { "enum": ["api_key", "assertion", "token_exchange", "none"] } },
        "signature_algorithms": { "type": "array", "items": { "enum": ["ed25519", "ecdsa-p256-sha256"] } } } },
    "digests": {
      "type": "object", "required": ["catalog", "keys", "blocks", "revocations"],
      "properties": {
        "catalog":     { "type": "string", "maxLength": 128 },
        "keys":        { "$ref": "#/$defs/version" },
        "blocks":      { "$ref": "#/$defs/version" },
        "revocations": { "$ref": "#/$defs/version" } } },
    "member_record": {
      "type": "object",
      "required": ["type", "net", "name", "url", "mcp_path", "kind", "protocol_versions",
                   "features", "user_identity", "incarnation", "seq", "digests", "leaving", "issued_at"],
      "properties": {
        "type":     { "const": "member" },
        "net":      { "$ref": "#/$defs/net_name" },
        "name":     { "$ref": "#/$defs/instance_name" },
        "url":      { "type": "string", "format": "uri", "pattern": "^https?://[^/?#]+(/[^?#]*[^/?#])?$" },
        "mcp_path": { "type": "string", "pattern": "^/" },
        "region":   { "type": "string", "maxLength": 64 },
        "labels":   { "type": "object", "maxProperties": 32,
                      "additionalProperties": { "type": "string", "maxLength": 128 } },
        "kind":     { "enum": ["sajha", "agent", "sponsored"] },
        "protocol_versions": { "type": "array", "minItems": 1, "items": { "type": "integer", "minimum": 1 } },
        "features": { "type": "array", "items": { "type": "string" }, "uniqueItems": true },
        "user_identity": { "type": "array", "items": { "type": "string" } },
        "incarnation": { "$ref": "#/$defs/version" },
        "seq":      { "$ref": "#/$defs/version" },
        "digests":  { "$ref": "#/$defs/digests" },
        "leaving":  { "type": "boolean" },
        "issued_at": { "$ref": "#/$defs/timestamp" } } },
    "member_entry": {
      "type": "object", "required": ["record", "signature", "state"],
      "properties": {
        "record":      { "$ref": "#/$defs/member_record" },
        "signature":   { "$ref": "#/$defs/signature" },
        "certificate": { "$ref": "#/$defs/cert_chain" },
        "state":       { "enum": ["alive", "suspect", "dead", "left"] },
        "reported_by": { "$ref": "#/$defs/instance_name" },
        "reported_at": { "$ref": "#/$defs/timestamp" } } },
    "problem": {
      "type": "object", "required": ["type", "status", "reason"],
      "properties": {
        "type":   { "type": "string", "pattern": "^urn:sajha:net:error:[a-z_]+$" },
        "title":  { "type": "string" },
        "status": { "type": "integer" },
        "reason": { "type": "string", "pattern": "^[a-z_]+$" },
        "detail": { "type": "string", "maxLength": 1024 },
        "supported_versions": { "type": "array", "items": { "type": "integer" } } } }
  }
}
```

The key record, blocks document, revocation list and user assertion schemas are in their own
sections and belong to the same `$defs` (`key_record`, `blocks_document`, `revocation_list`,
`user_assertion`).

## 8. Certificates and signatures

### 8.1 Certificate profile

Every participant holds an X.509 v3 certificate issued by the net CA (or, in manual mode, §8.11,
self-signed and pinned):

- **Subject** `O=<net name>, CN=<instance name>` (UTF8String), exactly as written in §5.
- **subjectAltName** names the host of the participant's `url`: a `dNSName` for a host name, an
  `iPAddress` for an address. A receiver MUST refuse a member record whose `url` host is not in the
  certificate's subjectAltName (this is what stops a member advertising someone else's address).
- **keyUsage** `digitalSignature` (critical); **basicConstraints** `cA=false` (critical).
- Public key: Ed25519 or ECDSA P-256 (§8.2). Validity at most the net's configured certificate
  lifetime (the design's default is 30 days).
- The CA certificate has `O=<net name>`, `basicConstraints cA=true, pathLen=0` (or larger when the
  net uses intermediates), `keyUsage keyCertSign, cRLSign`.

A participant MUST accept a certificate only if it chains to the configured net CA certificate, is
within its validity period, has `O` equal to the receiver's net name, and is not revoked (§13).

**Key id.** The `keyid` of a certificate is `base64url(SHA-256(DER of the leaf certificate))`
(the `x5t#S256` thumbprint).

### 8.2 Algorithms

| `alg` (RFC 9421 registry) | Key | Signature encoding | Status |
|---|---|---|---|
| `ed25519` | Ed25519 (RFC 8032) | 64 raw bytes | MUST verify; MUST be able to sign; RECOMMENDED for new keys |
| `ecdsa-p256-sha256` | ECDSA P-256 with SHA-256 | 64 bytes, `r ‖ s`, each 32 bytes big-endian (not DER) | MUST verify; MAY sign |

The `alg` parameter MUST be present and MUST match the certificate's key type; a mismatch is
`signature_invalid`. No other algorithm (in particular no HMAC and no RSA) is allowed in version 1.

### 8.3 The certificate header

```
Sajha-Net-Certificate: :MIIBSTCB/KADAgECAgMaKzwwBQYDK2Vw...:, :MIIBJjCB2aAD...:
```

An RFC 8941 List of Byte Sequences: the sender's DER certificate first, then any intermediates, never
the root. It MUST be on every signed request and response. The certificate is bound to the signature
through `keyid` (the leaf's thumbprint, inside the covered signature parameters), so the header
itself is not a covered component.

### 8.4 Content digest

Every signed request and response that has a body carries `Content-Digest` (RFC 9530) with the
`sha-256` algorithm over the body bytes as sent (after any content coding is removed by the
receiver's HTTP stack, before JSON parsing):

```
Content-Digest: sha-256=:GmWE8ztwdAgAKupEUE8ySGW/GDF1N4TRv6PSGmbSBl8=:
```

Receivers MUST recompute it and refuse a mismatch (`digest_mismatch`). Other digest algorithms MAY
be present and are ignored. A GET has no body and no `Content-Digest`.

### 8.5 Request signatures

Requests are signed with RFC 9421 HTTP Message Signatures under the signature label **`sajhanet`**.
The covered components are, in this order:

| Component | When |
|---|---|
| `"@method"` | always |
| `"@path"` | always |
| `"@query"` | always (`?` when there is no query) |
| `"content-type"` | when there is a body |
| `"content-digest"` | when there is a body |
| `"mcp-protocol-version"`, `"mcp-method"`, `"mcp-name"` | on the MCP endpoint, when present |
| `"mcp-session-id"` | on the MCP endpoint, 2025-11-25 era, when present |
| every `"mcp-param-*"` header | on the MCP endpoint, when present (arguments mirrored by `x-mcp-header`) |
| `"sajha-net-version"` | always |
| `"sajha-net-from"` | always: the sender's instance name |
| `"sajha-net-to"` | always: the receiver's instance name |
| `"sajha-net-hop"`, `"sajha-net-visited"` | forwarded tool calls (§15.2) |
| `"sajha-net-api-key"` | when present (§15.3) |
| `"sajha-net-user-assertion"` | when present (§15.5) |
| `"traceparent"` | when present (always on forwarded tool calls) |

`@authority` and `@scheme` are deliberately **not** covered, because TLS often ends at a proxy that
changes them. `Sajha-Net-To` binds the request to its recipient instead.

The signature parameters are:

| Parameter | Rule |
|---|---|
| `created` | REQUIRED. Integer seconds since the epoch at signing. |
| `nonce` | REQUIRED on requests. At least 16 random bytes, base64url, at most 64 characters. Never reused by a sender. |
| `keyid` | REQUIRED. The leaf certificate's thumbprint (§8.1). |
| `alg` | REQUIRED. §8.2. |
| `tag` | REQUIRED. `"sajha-net-v1"`. |
| `expires` | OPTIONAL. If present, receivers MUST also refuse after it. |

The headers carrying the result:

```
Signature-Input: sajhanet=("@method" "@path" "@query" "content-type" "content-digest" "sajha-net-version" "sajha-net-from" "sajha-net-to");created=1791374400;nonce="q1QXbXk3WlNQ8n0Zr6dL4w";keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"
Signature: sajhanet=:<base64 signature>:
```

Other signatures under other labels MAY be present and are ignored.

### 8.6 Header field formats

| Header | Format |
|---|---|
| `Sajha-Net-Version` | RFC 8941 Integer (`1`) |
| `Sajha-Net-From`, `Sajha-Net-To` | the instance name as written in §5.2 (ASCII), not quoted |
| `Sajha-Net-Hop` | RFC 8941 Integer, at least 1 |
| `Sajha-Net-Visited` | RFC 8941 List of Strings (`"risk-eu", "treasury-na"`) |
| `Sajha-Net-Api-Key` | the raw API key, ASCII |
| `Sajha-Net-User-Assertion` | base64url of the JCS bytes of a signed user assertion (§15.5) |
| `Sajha-Net-Certificate` | §8.3 |

Component values in the signature base are the field values with leading and trailing whitespace
removed, as RFC 9421 §2.1 specifies; senders MUST send each of these headers exactly once.

### 8.7 Verifying a request

A receiver MUST perform these checks, and refuse at the first failure with the `reason` shown (HTTP
status per §7.4; JSON-RPC `-32014` on the MCP endpoint):

1. `Signature-Input` and `Signature` carry the `sajhanet` label, and `Sajha-Net-Certificate` is
   present → else `signature_missing`.
2. `tag` is `sajha-net-v1`; `created`, `nonce`, `keyid` and `alg` are present; every component
   §8.5 requires for this request is covered → else `signature_incomplete`.
3. `Sajha-Net-Version` is a version the receiver speaks → else `unsupported_version`.
4. `created` is not more than the maximum age before receipt (SAJHA:
   `sajhanet.identity.signature_max_age_seconds`, design default 30 s; never more than 300 s) and not
   more than 5 s after receipt; `expires`, if present, has not passed → else `signature_expired`.
5. `Content-Digest` matches the body → else `digest_mismatch`.
6. The certificate chain is valid for the net (§8.1) → else `certificate_invalid`; its `O` is the
   receiver's net → else `net_mismatch`.
7. Neither the certificate's serial nor its `CN` is on the current revocation list (§13) → else
   `certificate_revoked` or `instance_revoked`.
8. `keyid` equals the leaf's thumbprint and `alg` matches its key → else `signature_invalid`.
9. The signature verifies over the RFC 9421 signature base → else `signature_invalid`.
10. `Sajha-Net-From` equals the certificate's `CN` → else `from_mismatch`; `CN` is not the receiver's
    own name → else `name_conflict`; `Sajha-Net-To` equals the receiver's own name → else
    `recipient_mismatch`.
11. The pair (`keyid`, `nonce`) has not been seen within the replay window → else `replay`. Only
    after every check above passes, record the pair for the replay window.

The **replay window** is the maximum age plus the 5 s future allowance. A participant with several
workers MUST keep seen nonces where every worker sees them (SAJHA: the state store).

### 8.8 Response signatures

Every response to a signed request MUST be signed by the responder, under the label `sajhanet`,
covering, in order:

```
("@status" "content-type" "content-digest" "sajha-net-version" "sajha-net-from" "sajha-net-to" "signature";req;key="sajhanet")
```

with `created`, `keyid`, `alg` and `tag` as in §8.5 (`nonce` is not needed: the response is bound to
the request through the request's own signature, `"signature";req;key="sajhanet"`). On a response
`Sajha-Net-From` is the responder and `Sajha-Net-To` the requester. `content-type` and
`content-digest` are omitted when there is no body. The response carries `Sajha-Net-Certificate`.

The requester MUST verify the response as in §8.7 steps 4 to 10 (with `Sajha-Net-From` equal to the
participant it asked) and MUST discard a response that fails. A requester that receives an unsigned
error from an intermediary proxy (for example a `502`) treats it as a transport failure, not as an
answer from the peer.

### 8.9 Streamed responses

A forwarded MCP call may be answered with `text/event-stream`. Its HTTP response is signed as in §8.8
without `content-digest`. Because the events are not covered by that signature, the **final**
JSON-RPC response in the stream (the one with the request's `id`) MUST carry a message signature:

- in `result._meta["io.sajha/net"].response_signature`, or for an error in
  `error.data["io.sajha/net"].response_signature`;
- the value is a `signature` object (§7.6) plus `"request_nonce"`, the nonce of the request;
- the signing input is `sajha-net-v1:response:<request_nonce>:` followed by the JCS bytes (§8.10) of
  the whole JSON-RPC response object with the `response_signature` member removed.

The home MUST verify it before using the result. Progress and log notifications in the stream are not
signed; they are advisory and MUST NOT change what the home does with the result.

A JSON (non-streamed) response MAY also carry `response_signature`; it is then checked the same way.

### 8.10 Record signatures (JCS)

Objects that are stored and passed on by others (member records, key records, blocks documents, the
revocation list, user assertions) carry their own signature so that any holder can verify them later:

- The object has a `type` member (`member`, `key`, `blocks`, `revocations`, `assertion`).
- **Signing input:** the ASCII bytes `sajha-net-v1:<type>:` followed by the RFC 8785 (JCS)
  canonical UTF-8 serialization of the object **without** its `signature` member. The `type` prefix
  is domain separation: a valid signature over one kind of record never verifies as another.
- The signature is placed in the object's `signature` member (`urn:sajha:net:v1#/$defs/signature`),
  except for member records, whose signature sits beside the record in the member entry (§9.2).
- `keyid` names the signer's certificate (§8.1); for the revocation list it is the CA certificate's
  thumbprint.
- Numbers in signed records are integers (no fractions), so implementations do not depend on
  floating-point formatting for JCS.

A verifier MUST check the signature against a certificate that was valid for the signer's instance
name (the record's `name`, `home_instance` or `instance`, as each section says) and MUST recompute
JCS itself rather than trusting the received byte order.

### 8.11 Manual mode

A net may run without a CA (design §6.5). Each participant then uses a **self-signed** certificate
with the profile of §8.1, and each administrator pins the thumbprints of the peers they approve. Step 6
of §8.7 becomes "the leaf's thumbprint is pinned", step 7 is skipped (removing a pin is the
revocation), and §13 and §14 do not apply. Everything else is unchanged.

## 9. Membership

Membership follows SWIM (failure detection by direct and indirect probes, infection-style
dissemination) with anti-entropy. Gossip carries only membership and digests; tools, schemas and keys
are pulled point to point.

### 9.1 Member record

A participant describes itself in a **member record**, signed by itself (`type: "member"`, §8.10):

```json
{
  "type": "member",
  "net": "acme-net",
  "name": "risk-eu",
  "url": "https://sajha-risk-eu.example.internal",
  "mcp_path": "/mcp",
  "region": "eu-west",
  "labels": { "domain": "risk", "jurisdiction": "EU", "entity": "acme-eu" },
  "kind": "sajha",
  "protocol_versions": [1],
  "features": ["gossip", "catalog", "key_directory", "key_verification", "blocks", "residency"],
  "user_identity": ["api_key"],
  "incarnation": 1791370000000,
  "seq": 4,
  "digests": { "catalog": "sha256:7f3c09d2", "keys": 42, "blocks": 3, "revocations": 7 },
  "leaving": false,
  "issued_at": "2026-10-07T11:58:04Z"
}
```

- `digests.catalog` is an opaque string that MUST change whenever the catalog this participant
  exports to **any** peer may have changed (a tool, a schema, a description, health class or an export
  rule changed). `digests.keys` is its key-directory version (§11), `digests.blocks` its blocks
  version (§12), `digests.revocations` the version of the revocation list it holds (§13).
- `seq` increments every time the participant re-signs its record within one incarnation (a digest or
  label changed) and resets to 0 when the incarnation changes.
- A record is accepted only if its signature verifies against a certificate whose `CN` equals
  `name` and whose subjectAltName contains the host of `url`.

### 9.2 Member entry and states

What travels in gossip is a **member entry**: the subject's signed record, the subject's certificate
chain, and the sender's view of its state (`urn:sajha:net:v1#/$defs/member_entry`).

| State | Meaning | Who may assert it |
|---|---|---|
| `alive` | Answering probes | the subject (by a new incarnation), or anyone repeating a record |
| `suspect` | Did not answer a direct or any indirect probe | any participant (`reported_by`) |
| `dead` | Suspect for longer than the suspect timeout without refuting | any participant |
| `left` | Departed cleanly | the subject only: valid only with a record whose `leaving` is `true` |

The state applies to the record's `incarnation`. `certificate` is REQUIRED in sync messages and
leave announcements and OPTIONAL in ping, ping-req and ack updates. A receiver that does not hold a
valid certificate for the record's `keyid` MUST NOT apply the entry and SHOULD run a sync (§9.7)
with the sender.

### 9.3 Incarnation

- The incarnation is a participant's own counter: milliseconds since the Unix epoch, chosen when its
  gossip agent starts as `max(now_ms, last_own_incarnation + 1)`, where `last_own_incarnation` is the
  value it persisted, if any. Deriving it from the start time makes it higher after a restart even
  when nothing was persisted; persisting it covers a clock that moved backwards.
- To refute a `suspect` or `dead` claim about itself at its current incarnation, a participant
  sets `incarnation = max(now_ms, incarnation + 1)`, `seq = 0`, re-signs its record and disseminates
  it with state `alive`.
- No participant ever changes another's incarnation; a record is the subject's own signed statement.

### 9.4 Merge rules

For an incoming entry U about instance X, against the held entry E:

1. Drop U if X is revoked (§13), the record's signature or certificate fails, or `record.net` is not
   the receiver's net. An entry about the receiver itself is never merged into its own record; it
   is handled by rule 6.
2. If no E is held: accept U.
3. If `U.record.incarnation > E.record.incarnation`: replace E with U (record and state).
4. If equal incarnation:
   - the record with the higher `seq` is kept (equal `seq` with different content: keep E);
   - the state becomes the higher in the precedence `alive < suspect < dead < left`.
5. If `U.record.incarnation < E.record.incarnation`: ignore U.
6. A participant that receives `suspect` or `dead` about **itself** at its current incarnation refutes
   (§9.3). It ignores claims about older incarnations of itself.

Every participant applying these rules converges on the same view without coordination. Changes that
result from a merge are queued for dissemination (§9.6).

### 9.5 Ping, ack and ping-req

Every gossip interval (SAJHA: `sajhanet.gossip.gossip_interval_ms`), a participant picks one member
in state `alive` or `suspect` at random (round-robin over a shuffled list is RECOMMENDED) and sends a
ping. Members in `dead` are probed at the much lower dead-probe rate until their retention ends
(§9.9).

`POST /sajhanet/v1/gossip/ping`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ping request",
  "type": "object", "required": ["type", "seq", "updates"],
  "properties": {
    "type":    { "const": "ping" },
    "seq":     { "type": "integer", "minimum": 0 },
    "updates": { "type": "array", "maxItems": 32, "items": { "$ref": "urn:sajha:net:v1#/$defs/member_entry" } }
  }
}
```

Response (the **ack**):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ack",
  "type": "object", "required": ["type", "seq", "updates"],
  "properties": {
    "type":      { "const": "ack" },
    "seq":       { "type": "integer", "minimum": 0 },
    "target":    { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "reachable": { "type": "boolean" },
    "updates":   { "type": "array", "maxItems": 32, "items": { "$ref": "urn:sajha:net:v1#/$defs/member_entry" } }
  }
}
```

The responder MUST include its own current entry among the `updates` of every ack if its record
changed since it last sent one to this peer, and SHOULD include it at least once per suspect timeout
regardless.

If no valid ack arrives within the ping timeout (SAJHA: `ping_timeout_ms`), the prober sends
`POST /sajhanet/v1/gossip/ping-req` to k other members chosen at random (SAJHA: `indirect_probes`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "ping-req request",
  "type": "object", "required": ["type", "seq", "target", "updates"],
  "properties": {
    "type":    { "const": "ping-req" },
    "seq":     { "type": "integer", "minimum": 0 },
    "target":  { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "updates": { "type": "array", "maxItems": 32, "items": { "$ref": "urn:sajha:net:v1#/$defs/member_entry" } }
  }
}
```

The intermediary MUST resolve `target` to a member it already holds and use **that member's signed
`url`**; it MUST answer `400 unknown_member` for any other target and MUST NOT accept a URL in the
request. It pings the target itself and answers with an ack carrying `target` and `reachable`
(`true` if the target acked within the ping timeout). It SHOULD answer within twice the ping timeout.

If neither the direct ping nor any ping-req yields `reachable: true` within the protocol period, the
prober marks the target `suspect` (with itself as `reported_by`). A suspect not refuted within the
suspect timeout (SAJHA: `suspect_timeout_seconds`) becomes `dead`.

### 9.6 Dissemination

Changes (new or changed records, state changes) are piggybacked on the `updates` of pings, ping-reqs
and acks. Each change is sent at most `λ × ⌈log2(n + 1)⌉` times, with n the number of members and λ = 3
by default. When more changes are queued than fit, a sender picks those sent the fewest times,
preferring changes whose `digests.revocations` or `digests.keys` increased (revocations spread with
priority, design §10.3).

### 9.7 Sync and join

`POST /sajhanet/v1/membership/sync` is a push-pull of the whole list. It is used:

- **to join**: on start-up, to the last-known members first, then the configured seeds, then any
  discovery plug-in (design §6.6), until one answers (`reason: "join"`);
- **for anti-entropy**: every full-sync interval (SAJHA: `sajhanet.gossip.full_sync_interval_seconds`)
  with one random member (`reason: "anti_entropy"`);
- when a receiver lacks a certificate it needs (§9.2).

Request and response:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "sync request and response",
  "type": "object", "required": ["type", "members"],
  "properties": {
    "type":    { "const": "sync" },
    "reason":  { "enum": ["join", "anti_entropy", "certificate", "rejoin"] },
    "members": { "type": "array", "maxItems": 1024,
                 "items": { "allOf": [ { "$ref": "urn:sajha:net:v1#/$defs/member_entry" },
                                       { "required": ["certificate"] } ] } }
  }
}
```

The request carries the sender's whole list, including its own entry; the response carries the
receiver's whole list after merging the request. Both sides then merge (§9.4). The responder MUST
include `dead` and `left` entries still in retention, so a rejoining participant learns of them.

### 9.8 Leave

A participant that stops cleanly re-signs its record with `leaving: true` (same incarnation,
`seq + 1`) and sends `POST /sajhanet/v1/membership/leave` to at least three members (all members, when
there are fewer):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "leave request",
  "type": "object", "required": ["type", "entry"],
  "properties": {
    "type":  { "const": "leave" },
    "entry": { "allOf": [ { "$ref": "urn:sajha:net:v1#/$defs/member_entry" },
                          { "required": ["certificate"],
                            "properties": { "state": { "const": "left" },
                                            "record": { "properties": { "leaving": { "const": true } } } } } ] }
  }
}
```

Response: `{}`. Receivers mark the member `left` at once and disseminate the entry. A receiver MUST
refuse a leave whose record is not signed by the sender itself (`invalid_request`).

### 9.9 Retention, restarts and dead probing

- `dead` and `left` entries are kept for the dead-retention period (SAJHA:
  `sajhanet.gossip.dead_retention_minutes`) and then removed. During retention, members probe a dead
  member's last `url` at the dead-probe interval, so a restarted participant whose seeds are all down
  is still found.
- A participant persists the last membership list it saw and its own last incarnation, and on start
  contacts the persisted members before its seeds (§9.7).
- A participant whose certificate is not from the net CA cannot ping, sync or be pinged: every one of
  these requests is signed and checked (§8.7).

## 10. Catalog exchange

### 10.1 When to pull

A participant pulls a peer's catalog when it first learns of the peer, when the peer's
`digests.catalog` differs from the value it held at its last successful pull, and at least once per
fallback refresh interval (SAJHA: `sajhanet.refresh_interval_seconds`). It MUST NOT pull from a peer
it has blocked entirely or outbound.

### 10.2 The catalog endpoint

`POST /sajhanet/v1/catalog`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "catalog request",
  "type": "object",
  "properties": { "if_none_match": { "type": "string", "maxLength": 128 } }
}
```

Response:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "catalog response",
  "type": "object", "required": ["instance", "catalog_digest", "hash", "unchanged"],
  "properties": {
    "instance":       { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "catalog_digest": { "type": "string", "maxLength": 128 },
    "hash":           { "type": "string", "pattern": "^sha-256:[A-Za-z0-9_-]{43}$" },
    "generated_at":   { "$ref": "urn:sajha:net:v1#/$defs/timestamp" },
    "unchanged":      { "type": "boolean" },
    "tools": {
      "type": "array",
      "items": {
        "type": "object", "required": ["name", "inputSchema", "_meta"],
        "description": "An MCP Tool object exactly as tools/list would return it to this peer",
        "properties": {
          "_meta": { "type": "object", "required": ["io.sajha/net"],
                     "properties": { "io.sajha/net": { "$ref": "#/$defs/tool_net_meta" } } } } } }
  },
  "$defs": {
    "tool_net_meta": {
      "type": "object", "required": ["instance"],
      "properties": {
        "instance":       { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
        "region":         { "type": "string" },
        "labels":         { "type": "object", "additionalProperties": { "type": "string" } },
        "version":        { "type": "string" },
        "deprecated":     { "type": "boolean" },
        "data_classes":   { "type": "object",
                            "properties": { "arguments": { "type": "array", "items": { "type": "string" } },
                                            "results":   { "type": "array", "items": { "type": "string" } } } },
        "llm_tool":       { "type": "boolean" },
        "latency_ms_p50": { "type": "integer", "minimum": 0 },
        "health":         { "enum": ["ok", "degraded", "down"] },
        "per_user_results": { "type": "boolean" },
        "schema_hash":    { "type": "string" },
        "description_hash": { "type": "string" },
        "origin":         { "$ref": "urn:sajha:net:v1#/$defs/instance_name" }
      } }
  }
}
```

- `tools` lists exactly the tools the responder's export rules let **the requesting participant** see
  for at least one of its users (design §11.2). It is present unless `unchanged` is `true`.
- `hash` is `sha-256:` + base64url of SHA-256 over the JCS bytes of the `tools` array, the array
  sorted by `name`. If `if_none_match` equals the hash the response would have, the responder answers
  `{"unchanged": true, ...}` without `tools`.
- `catalog_digest` is the responder's current `digests.catalog`.
- Each tool's `_meta["io.sajha/net"]` is set by the host: `instance` (itself), `data_classes`
  (a summary; the authoritative marks are `x-sajha-data-class` on schema properties, design §12),
  `llm_tool`, health and latency, `per_user_results` (results differ per user, so a home cache must be
  keyed by user), hashes of the schema and description, and `origin` only for a re-exported tool
  (§16).
- Descriptions and schemas are untrusted input at the receiver (§19), which screens and caps them.

### 10.3 What the home adds

When a home lists its proxies in its own `tools/list`, it sets in `_meta["io.sajha/net"]` the host's
fields plus `locality` (`"remote"`; `"local"` MAY be set on its own tools), `qualified_name`,
`host_tool` (the host's name), `alias` when a bare alias is offered, and `state` when the proxy is not
`active` (`unconfirmed`, `unavailable`, `held`). This is the object shown in the design's §8.3.

### 10.4 Relationship to `tools/list`

A signed `tools/list` request (§8.5) from a participant to a host's MCP endpoint, with no user
identity headers, MUST return the same set of tools, with the same `_meta["io.sajha/net"]`, as
`/sajhanet/v1/catalog` returns to that participant (pagination per MCP). The catalog endpoint is the
REQUIRED way for net-native participants because it supports `if_none_match` and a single hash; the
`tools/list` form exists so a sponsor or generic MCP tooling can read a net catalog with ordinary MCP
calls.

### 10.5 Visibility

A home needs to hide proxies a user could not call (design §11.3: users without an account on the
host do not see its tools). With feature `visibility`:

`POST /sajhanet/v1/catalog/visibility`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "visibility request",
  "type": "object", "required": ["key_ids"],
  "properties": { "key_ids": { "type": "array", "minItems": 1, "maxItems": 100, "items": { "type": "string" } } }
}
```

Response:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "visibility response",
  "type": "object", "required": ["visibility"],
  "properties": {
    "visibility": { "type": "object",
      "additionalProperties": { "type": "object",
        "properties": {
          "tools":  { "type": "array", "items": { "type": "string" } },
          "reason": { "type": "string" } } } }
  }
}
```

For each key id the host resolves the key's owner through its key directory (only keys whose
`home_instance` is the requester; others get `reason: "not_home"`), maps the user as for a call
(design §11.3), and lists the host tool names that user may call, or none with a `reason`
(`no_account`, `blocked`, `key_unusable`). The answer is advice for display; every call is still
authorized by the host (§15.4).

## 11. Net key directory

### 11.1 Key record

Each participant with feature `key_directory` publishes one record per API key it issued, signed by
itself (`type: "key"`, §8.10). The raw key is never in a record.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sajha:net:v1#/$defs/key_record",
  "type": "object",
  "required": ["type", "key_id", "key_prefix", "name", "key_hash", "home_instance", "owner", "enabled",
               "expires_at", "revoked_at", "tool_access_mode", "tool_access_list", "persistent",
               "version", "updated_at", "signature"],
  "properties": {
    "type":          { "const": "key" },
    "key_id":        { "type": "string", "maxLength": 64 },
    "key_prefix":    { "type": "string", "maxLength": 16 },
    "name":          { "type": "string", "maxLength": 255 },
    "key_hash":      { "type": "string", "pattern": "^[0-9a-f]{64}$" },
    "home_instance": { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "owner": { "type": "object", "required": ["user_id", "user_name", "roles"],
      "properties": {
        "user_id":      { "type": "string" },
        "user_name":    { "type": "string" },
        "display_name": { "type": "string" },
        "roles":        { "type": "array", "items": { "type": "string" } } } },
    "enabled":       { "type": "boolean" },
    "expires_at":    { "anyOf": [ { "$ref": "urn:sajha:net:v1#/$defs/timestamp" }, { "type": "null" } ] },
    "revoked_at":    { "anyOf": [ { "$ref": "urn:sajha:net:v1#/$defs/timestamp" }, { "type": "null" } ] },
    "tool_access_mode": { "enum": ["all", "allowlist", "denylist"] },
    "tool_access_list": { "type": "array", "items": { "type": "string" } },
    "persistent":    { "type": "boolean" },
    "version":       { "$ref": "urn:sajha:net:v1#/$defs/version" },
    "updated_at":    { "$ref": "urn:sajha:net:v1#/$defs/timestamp" },
    "signature":     { "$ref": "urn:sajha:net:v1#/$defs/signature" }
  }
}
```

- `key_hash` is the lowercase hex SHA-256 of the raw key's UTF-8 bytes (what SAJHA already stores,
  `sajha/security.py`). Because it is unsalted, keys MUST carry at least 128 bits of randomness.
- `version` comes from **one counter per home** that increases on every change to any of its records;
  the home's directory version (`digests.keys`) is the highest `version` it has issued.
- A deleted key is never removed from the directory: its record gets `revoked_at` and a new
  `version`.
- `tool_access_mode` and `tool_access_list` are a ceiling on what the key may call anywhere; they
  name tools by their names **at the home** (qualified names for proxies).

### 11.2 Acceptance

A receiver MUST accept a record only if it was returned by its `home_instance` (the responder's
`Sajha-Net-From`, §11.3) and its signature verifies against a valid certificate of `home_instance`.
Records about one home arriving from anyone else are ignored. A record with a lower or equal `version`
than the held one is ignored. When a certificate serial is revoked (§13), a receiver MUST discard the
records that certificate signed and re-pull that home's directory from version 0.

When a home leaves or is revoked, its records become unusable everywhere (they are kept, marked, and
refuse every forwarded key).

### 11.3 Delta pull

When a peer's `digests.keys` exceeds the version a participant holds for it, the participant pulls
from that peer: `POST /sajhanet/v1/keys`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "key delta request",
  "type": "object", "required": ["since"],
  "properties": {
    "since": { "$ref": "urn:sajha:net:v1#/$defs/version" },
    "limit": { "type": "integer", "minimum": 1, "maximum": 1000 }
  }
}
```

Response:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "key delta response",
  "type": "object", "required": ["home_instance", "version", "records", "more"],
  "properties": {
    "home_instance": { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "version":    { "$ref": "urn:sajha:net:v1#/$defs/version" },
    "records":    { "type": "array", "items": { "$ref": "urn:sajha:net:v1#/$defs/key_record" } },
    "more":       { "type": "boolean" },
    "next_since": { "$ref": "urn:sajha:net:v1#/$defs/version" }
  }
}
```

`records` are the responder's own records with `version > since`, in ascending `version`, at most
`limit` (default 500). When `more` is true, the requester continues with `since = next_since`.
`version` is the responder's directory version at the time of the response.

### 11.4 Digest and anti-entropy

`POST /sajhanet/v1/keys/digest` with body `{}` returns:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "key digest response",
  "type": "object", "required": ["home_instance", "version", "count", "root"],
  "properties": {
    "home_instance": { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "version": { "$ref": "urn:sajha:net:v1#/$defs/version" },
    "count":   { "type": "integer", "minimum": 0 },
    "root":    { "type": "string", "pattern": "^[A-Za-z0-9_-]{43}$" }
  }
}
```

`root` is base64url(SHA-256(JCS of the array of `[key_id, version]` pairs of all the home's records,
sorted by `key_id`)). Every key-directory full-sync interval (SAJHA:
`sajhanet.key_directory.full_sync_interval_seconds`, separate from gossip's own anti-entropy, which
exchanges only the versions in `digests`) a participant fetches each home's digest and compares it
with the same computation over the records it holds for that home; on any difference it re-pulls
with `since: 0`.

## 12. Block publication

Blocks are local decisions (design §11.4) published so every console can draw the whole picture. A
participant with feature `blocks` serves `POST /sajhanet/v1/blocks` (body `{}`), returning its blocks
document, signed by itself (`type: "blocks"`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sajha:net:v1#/$defs/blocks_document",
  "type": "object", "required": ["type", "instance", "version", "blocks", "signature"],
  "properties": {
    "type":     { "const": "blocks" },
    "instance": { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "version":  { "$ref": "urn:sajha:net:v1#/$defs/version" },
    "blocks": { "type": "array", "maxItems": 1000, "items": {
      "type": "object", "required": ["id", "level", "target_instance", "set_at"],
      "properties": {
        "id":              { "type": "string" },
        "level":           { "enum": ["instance", "inbound", "outbound", "tool", "user"] },
        "target_instance": { "anyOf": [ { "$ref": "urn:sajha:net:v1#/$defs/instance_name" }, { "const": "*" } ] },
        "tool":            { "type": "string" },
        "user":            { "type": "string" },
        "reason":          { "type": "string", "maxLength": 500 },
        "set_at":          { "$ref": "urn:sajha:net:v1#/$defs/timestamp" },
        "expires_at":      { "$ref": "urn:sajha:net:v1#/$defs/timestamp" } } } },
    "signature": { "$ref": "urn:sajha:net:v1#/$defs/signature" }
  }
}
```

- `level` `tool` names a host tool with `tool` (for an inbound block) or a remote tool by qualified
  name (for an outbound hide); `user` names a net user (`alice@risk-eu`).
- `version` equals the publisher's `digests.blocks`; peers pull when it increases. Expired blocks are
  omitted. `reason` MAY be withheld.
- A block is **enforced only by the participant that set it**; a published block never changes what
  another participant does.

## 13. Revocation list

The CA participant maintains the net's revocation list, signed with the CA key (`type:
"revocations"`, `keyid` the CA certificate's thumbprint):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sajha:net:v1#/$defs/revocation_list",
  "type": "object", "required": ["type", "net", "version", "issued_at", "revoked", "signature"],
  "properties": {
    "type":      { "const": "revocations" },
    "net":       { "$ref": "urn:sajha:net:v1#/$defs/net_name" },
    "version":   { "$ref": "urn:sajha:net:v1#/$defs/version" },
    "issued_at": { "$ref": "urn:sajha:net:v1#/$defs/timestamp" },
    "revoked": { "type": "array", "items": {
      "type": "object", "required": ["revoked_at"],
      "anyOf": [ { "required": ["instance"] }, { "required": ["serial"] } ],
      "properties": {
        "instance":   { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
        "serial":     { "type": "string", "pattern": "^[0-9a-f]+$" },
        "revoked_at": { "$ref": "urn:sajha:net:v1#/$defs/timestamp" },
        "reason":     { "type": "string", "maxLength": 200 } } } },
    "signature": { "$ref": "urn:sajha:net:v1#/$defs/signature" }
  }
}
```

- An entry with `instance` revokes every certificate naming that instance (removal from the net); an
  entry with `serial` (lowercase hex) revokes one certificate (a lost key, re-issued under the same
  name).
- Every participant serves `GET /sajhanet/v1/revocations`, returning the newest list it holds; because
  the list is CA-signed, it may be fetched from any member. A participant fetches it when a member's
  `digests.revocations` exceeds its own, and accepts it only if the signature verifies against the
  CA certificate, `net` matches and `version` is higher than the one it holds.
- A participant MUST start with the list from its configuration (SAJHA:
  `sajhanet.identity.revocation_list_ref`) when it has no newer one, and MUST apply a newer list to
  every subsequent request (§8.7 step 7), drop the revoked members (§9.4) and remove their tools.

## 14. Certificate enrollment and renewal

These endpoints are served only by the participant with feature `ca`. How a new participant obtains
the enrollment token, the CA certificate and the CA participant's URL is out of band (an operator
copies them; design §6.4).

### 14.1 Enrollment

`POST /sajhanet/v1/ca/enroll`, **not** signed (the requester has no certificate yet), over HTTPS only:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "enroll request",
  "type": "object", "required": ["net", "instance", "token", "csr"],
  "properties": {
    "net":      { "$ref": "urn:sajha:net:v1#/$defs/net_name" },
    "instance": { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "token":    { "type": "string", "minLength": 22, "maxLength": 256 },
    "csr":      { "$ref": "urn:sajha:net:v1#/$defs/b64", "description": "DER PKCS#10 request" }
  }
}
```

The CA participant MUST check, refusing with `403 enrollment_refused` (one `reason` for every case, so
the response is no oracle; the `detail` is for the CA's own log only):

- the token exists, is unused, unexpired and was issued for this `net` and `instance` (compared in
  constant time);
- the CSR's self-signature verifies (proof that the requester holds the private key), its key is
  Ed25519 or P-256, and its subject is `O=<net>, CN=<instance>`;
- the requested subjectAltName names one host (DNS or IP); the CA MAY also require it to match a host
  bound to the token.

On success the token is spent (even if the response is then lost; the operator issues another) and the
response is:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "enroll and renew response",
  "type": "object", "required": ["certificate", "ca_certificate", "not_after"],
  "properties": {
    "certificate":    { "$ref": "urn:sajha:net:v1#/$defs/cert_chain" },
    "ca_certificate": { "$ref": "urn:sajha:net:v1#/$defs/b64" },
    "not_after":      { "$ref": "urn:sajha:net:v1#/$defs/timestamp" }
  }
}
```

The response is signed by the CA participant's own certificate (§8.8, with `Sajha-Net-To` set to the
requested instance name), which the requester verifies against the CA certificate it was given. The
CA participant MUST rate-limit enrollment per source address.

### 14.2 Renewal

`POST /sajhanet/v1/ca/renew`, signed with the requester's current, valid, unrevoked certificate:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "renew request",
  "type": "object", "required": ["csr"],
  "properties": { "csr": { "$ref": "urn:sajha:net:v1#/$defs/b64" } }
}
```

The CSR's subject MUST equal the signing certificate's subject (`403 enrollment_refused` otherwise).
A new key pair is RECOMMENDED for every renewal. The response is the enroll response. A participant
SHOULD renew when a third of its certificate's validity remains and keep trying with back-off; the old
certificate stays valid until its own `notAfter`, so old and new overlap without any extra rule.

## 15. Tool-call forwarding

### 15.1 Request

A home forwards a call to a proxy tool as an MCP `tools/call` to the host's MCP endpoint, in the era
chosen by §6.4, with `params.name` set to the **host's** tool name (not the qualified name) and the
arguments unchanged after the home's own checks. The home SHOULD add
`params._meta["io.sajha/net"] = {"home": "<home>", "qualified_name": "<prefix>__<tool>"}` for the
host's audit. Arguments travel in the body, covered by `Content-Digest`; any `Mcp-Param-*` headers
mirroring them are covered by the signature (§8.5).

### 15.2 Headers

| Header | Value | Required |
|---|---|---|
| `Sajha-Net-Version` | protocol version in use | yes |
| `Sajha-Net-From` | the sender (the home, or the intermediary on a re-exported call) | yes |
| `Sajha-Net-To` | the host | yes |
| `Sajha-Net-Hop` | 1 for a direct call; +1 at each re-export step (§16) | yes |
| `Sajha-Net-Visited` | the instances already passed, home first; length equals `Sajha-Net-Hop` | yes |
| `traceparent` (and `tracestate` if any) | W3C Trace Context; the same trace id on every hop; also mirrored in `params._meta.traceparent` | yes |
| `Sajha-Net-Api-Key` | the user's raw API key (§15.3) | with `api_key` identity on hop 1 |
| `Sajha-Net-User-Assertion` | a home-signed user assertion (§15.5) | with `assertion` identity, or on hop > 1 |
| `Sajha-Net-Certificate`, `Signature-Input`, `Signature`, `Content-Digest` | §8 | yes |

A net-signed request MUST NOT also carry `Authorization` or the host's ordinary API-key header
(SAJHA: `X-API-Key`); a host MUST refuse such a request (`-32013`, reason `ambiguous_credentials`).
A request to the MCP endpoint that carries any `Sajha-Net-*` header but fails §8.7 MUST be refused; it
is never served as an anonymous or ordinarily authenticated request.

### 15.3 Identity: `api_key`

- **Home.** It attaches the key the caller presented, or, for a caller signed in another way, the
  user's default API key decrypted from its vault (design §10.2). It MUST send the key only over
  HTTPS and only on hop 1, and MUST NOT log, store, trace or audit it (the key id and prefix may be
  recorded).
- **Host** (feature `key_verification`). It computes the key's `key_hash`, finds the record in its
  directory, and refuses with `-32013` unless: the record exists (`key_unknown`); `enabled` is true
  (`key_disabled`); `expires_at` is null or in the future (`key_expired`); `revoked_at` is null
  (`key_revoked`); and `home_instance` equals `Sajha-Net-From` (`key_not_from_home`: a key enters the
  net only through its issuer). The verified user is `<owner.user_name>@<home_instance>`, with
  `owner.roles` as recorded by the home and the key's tool access as an extra ceiling.
- The host then maps the user to a local identity (design §11.3: explicit link, name match, role map
  or refusal `no_account`).

### 15.4 Host processing order

A host MUST apply these steps in order and stop at the first refusal (codes in §17):

1. Verify the request (§8.7) → `-32014` (HTTP 401 or 403).
2. Protocol version → `-32017`.
3. Blocks on the sending participant, entire or inbound → `-32015`.
4. Hop and loop checks (§16) → `-32016`.
5. Identity (§15.3 or §15.5); `none` only if the host allows service calls from this peer → `-32013`.
6. Block on the remote user → `-32015`.
7. User mapping (link, name, role map; remote administrators per the host's setting) → `-32013 no_account`.
8. Block on the tool → `-32015`.
9. Export rules for this peer and this user → `-32011 export`.
10. The host's own access rules, policy engine and approvals → `-32011 access | policy | approval_required`.
11. Execute; audit with the trace id and the key id (never the key).
12. Residency of the result against the home's labels → `-32012 residency_result`, or redact.
13. Answer, signed (§8.8, §8.9), with `result._meta["io.sajha/net"]` carrying at least `instance` and,
    when known, `data_classes.results`.

A tool's own failure is an ordinary MCP result with `isError: true`, not a net refusal.

### 15.5 Identity: `assertion`

A **user assertion** is a record signed by the home (`type: "assertion"`, §8.10):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:sajha:net:v1#/$defs/user_assertion",
  "type": "object",
  "required": ["type", "iss", "user", "key_id", "aud", "iat", "exp", "jti", "trace_id", "signature"],
  "properties": {
    "type":     { "const": "assertion" },
    "iss":      { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "user":     { "type": "string" },
    "key_id":   { "type": "string" },
    "aud":      { "$ref": "urn:sajha:net:v1#/$defs/instance_name" },
    "iat":      { "type": "integer" },
    "exp":      { "type": "integer" },
    "jti":      { "type": "string", "minLength": 16 },
    "trace_id": { "type": "string", "pattern": "^[0-9a-f]{32}$" },
    "signature": { "$ref": "urn:sajha:net:v1#/$defs/signature" }
  }
}
```

`iat` and `exp` are epoch seconds with `exp − iat` at most 60. `aud` is the final host (the tool's
`origin` for a re-exported tool, §16). It is sent in `Sajha-Net-User-Assertion` as base64url of the JCS
bytes of the whole object including `signature`. The host verifies the signature against a valid
certificate of `iss`, checks `aud` is itself, the time window, that `jti` was not seen within the
window, that `trace_id` matches `traceparent`, and that the key record `key_id` of `home_instance =
iss` is usable (§15.3 checks other than possession). The user is `user`, which MUST equal
`<owner.user_name>@<iss>` of that record. Intermediaries forward the assertion unchanged.

### 15.6 Progress, cancellation, input and tasks

- With `progress` on both sides, the host's progress notifications are relayed to the caller; with
  `cancellation`, the caller's cancellation is relayed to the host, by the mechanism of the MCP era in
  use for that hop.
- With `mrtr`, an `input_required` result from the host is relayed to the caller, and the caller's
  answer is sent back to the host as a new signed request carrying the host's `requestState`; the host
  resolves the user again on that request.
- With `tasks`, a task created at the host is scoped to the resolved net user; the home relays
  `tasks/get`, `tasks/update` and `tasks/cancel` as signed requests with the same identity headers.
- A destructive tool still needs confirmation at the home (design §9); the host may require its own
  approval (`-32011 approval_required`).

### 15.7 What the home's caller sees

The home turns any net refusal, or a host it cannot reach, into an MCP tool result with
`isError: true`, a text content saying which side refused and why in words safe for the caller, and
`_meta["io.sajha/net"].refusal` holding the `data["io.sajha/net"]` object of §17. It never forwards
the host's raw error text unscreened.

## 16. Hops and loops

- A participant without feature `reexport` exports only its own tools, so every call is one hop.
- A participant with `reexport` MAY export tools it imported; such tools carry `origin` (the
  participant that really hosts them) in `_meta["io.sajha/net"]`. When forwarding one, it increments
  `Sajha-Net-Hop`, appends itself to `Sajha-Net-Visited`, sets `Sajha-Net-From` to itself, re-signs,
  and forwards the user assertion unchanged. It MUST NOT forward a raw API key.
- A home calling a tool with an `origin` MUST use the `assertion` identity, with `aud` = `origin`.
- Every receiver refuses with `-32016`: `hop_limit` when `Sajha-Net-Hop` exceeds its maximum (SAJHA:
  `sajhanet.max_hops`; never more than 8); `loop` when its own name is in `Sajha-Net-Visited`;
  `hop_inconsistent` when the list's length is not the hop count or its last element is not
  `Sajha-Net-From`.
- Calls made by a remote LLM tool for its own work start a new call chain at the host, but MUST carry
  the incoming hop count and visited list forward, so that remote LLM tools count toward the hop limit.

## 17. Error model

### 17.1 JSON-RPC errors on the MCP endpoint

Net refusals between participants are JSON-RPC errors. The codes sit in the implementation-defined
range `-32000..-32019` (2026-07-28 reserves `-32020..-32099`; SAJHA uses `-32001` and `-32010` there
already and never emits `-32002` on the modern path):

| Code | Class | `reason` values | Side | HTTP |
|---|---|---|---|---|
| `-32011` | Authorization refused | `export`, `access`, `policy`, `approval_required`, `remote_admin` | host | 200 |
| `-32012` | Residency refused | `residency_arguments` (home), `residency_result` (host) | either | 200 |
| `-32013` | Identity refused | `key_unknown`, `key_disabled`, `key_expired`, `key_revoked`, `key_not_from_home`, `no_account`, `assertion_invalid`, `https_required`, `anonymous`, `ambiguous_credentials` | host (home for `https_required`, `anonymous`) | 200 |
| `-32014` | Peer refused | the 401 and 403 reasons of §7.4 that apply to authentication and revocation | host | 401 or 403 as in §7.4 |
| `-32015` | Blocked | `instance`, `inbound`, `outbound`, `tool`, `user` | either | 200 |
| `-32016` | Hop refused | `hop_limit`, `loop`, `hop_inconsistent` | host | 200 |
| `-32017` | Version unsupported | `unsupported_version` | host | 400 |
| `-32018` | Import refused | `import` | home only; never sent between participants | — |
| `-32019` | Instance unavailable | `unreachable`, `timeout`, `circuit_open`, `unconfirmed`, `response_invalid` | home only | — |

A participant MUST recognise a net refusal by `error.data["io.sajha/net"]`, not by the code alone,
because other implementations may use the same range for other things:

```json
{
  "jsonrpc": "2.0", "id": 7,
  "error": {
    "code": -32013,
    "message": "Your API key is not recognised on cust-na",
    "data": { "io.sajha/net": {
      "reason": "key_unknown", "side": "host", "instance": "cust-na", "tool": "var_calc",
      "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736", "retryable": false } }
  }
}
```

| Field | Meaning |
|---|---|
| `reason` | REQUIRED; a value from the table (new values may be added, §4) |
| `side` | REQUIRED; `home` or `host` |
| `instance` | REQUIRED; the participant that refused |
| `tool` | the tool name at that participant, when there is one |
| `trace_id` | the trace id of the call |
| `retryable` | true only when the same request may succeed later unchanged (`timeout`, `unreachable`, `rate_limited`) |
| `supported_versions` | for `-32017` |
| `response_signature` | §8.9, when the error ends a stream |

`message` MUST be safe to show to the caller: no key, no hash, no internal host name, no policy text
the host considers private.

### 17.2 HTTP errors on `/sajhanet/`

As §7.4 and §7.5. The problem body is signed like any response.

## 18. Limits

Senders MUST NOT exceed, and receivers MUST accept at least, these sizes. A receiver MAY enforce
lower configured caps for catalogs (design §7.2, SAJHA `sajhanet.limits`), flagging the peer and
ignoring the excess rather than failing the exchange.

| Item | Limit |
|---|---|
| ping, ping-req or ack body | 64 KiB; at most 32 `updates` |
| sync body | 1 MiB; at most 1024 members |
| leave body | 16 KiB |
| catalog response | 8 MiB |
| key delta response | 1 MiB; at most 1000 records |
| visibility request | 100 key ids |
| blocks document | 256 KiB; at most 1000 blocks |
| revocation list | 1 MiB |
| `Sajha-Net-Certificate` header | 8 KiB; at most 4 certificates |
| all request headers together | 16 KiB |
| nonce | 22 to 64 base64url characters |
| signature maximum age | configurable, at most 300 s; future allowance 5 s |
| assertion lifetime | at most 60 s |
| hops | at most 8 |
| configured instance name | 2 to 32 characters (§5.2) |
| member `labels` | 32 labels, values up to 128 characters |
| qualified tool name | at most 128 characters; SHOULD be at most 64 (§5.3) |
| `digests.catalog` | at most 128 characters |

Oversized bodies get `413 too_large`.

## 19. Security considerations

- **Signatures prove the sender; TLS keeps the content private.** A forwarded API key appears in a
  header and in the sender's signature base. Participants MUST use HTTPS on every hop that carries a
  key, MUST NOT log signature bases or covered header values, and MUST keep the raw key in memory only
  for the duration of the call.
- **Every participant that receives a forwarded key could capture it.** This is accepted for a net of
  trusted participants (design §10.2). The key-from-home rule (§15.3) stops a captured key being used
  through any participant other than its issuer, and through the issuer only with a fresh signature by
  the issuer. A net that will not accept the exposure uses `assertion` identity everywhere.
- **Replay.** `created`, the nonce store and `Sajha-Net-To` stop a request being replayed to the same
  participant or redirected to another. Clocks MUST be synchronised (NTP); a participant whose clock
  is wrong by more than the maximum age cannot talk to the net, which is the safe failure.
- **Proxies.** Path-rewriting proxies break verification by design. Deploy the net endpoints and the
  MCP endpoint at the path in the member record's `url`.
- **Algorithm confusion.** Only the two algorithms of §8.2, the `alg` parameter MUST match the key,
  and no symmetric algorithm exists in version 1.
- **Gossip trust.** Member records are signed by their subjects, so no relay can change a member's
  URL, labels, features or digests. `suspect` and `dead` claims cannot be signed by the subject; a
  malicious member can raise false suspicion, which the subject refutes (§9.3) and indirect probes
  limit. `left` requires the subject's signature.
- **SSRF.** URLs come only from signed member records whose host is in the subject's certificate;
  ping-req targets are member names, never URLs; participants SHOULD also apply their outbound URL
  guard (SAJHA: federation's) to every peer URL.
- **Untrusted catalogs and results.** Descriptions, schemas and results from a peer are untrusted
  text: screen them for injected instructions, cap their size, validate schemas, and never let them
  widen tool annotations (a remote tool is at least `openWorldHint: true`).
- **Unsigned progress.** Progress and log notifications inside a stream are not individually signed
  (§8.9); they MUST NOT drive decisions.
- **Key directory privacy.** Records carry user names, display names and roles of every key owner in
  the net. They contain no keys, but they are sensitive: store them with the same care as user
  records, and do not expose them to non-administrators.
- **Unsalted key hashes.** Lookups by hash need a deterministic hash, so keys MUST have at least
  128 bits of entropy; a low-entropy key could be recovered from its hash.
- **Revocation latency.** Certificate revocation reaches participants at gossip speed, and a
  revoked participant can still reach a peer that has not yet seen the new list. API-key revocation is
  immediate across the net because keys enter only through their home.
- **Enrollment.** Tokens are bearer secrets: single use, short-lived, bound to a name, sent only over
  HTTPS, compared in constant time; the CA participant rate-limits enrollment and gives one refusal
  reason for every failure.
- **CA key.** Whoever holds it can admit participants. It never leaves the CA participant; certificates
  are short-lived so that re-keying the CA bounds the damage of a theft.
- **Tool-name prefixes.** Address names give prefixes that start with a digit. Some LLM providers
  require function names to start with a letter or underscore; a participant serving such a provider
  will need a configured instance name for every peer whose tools it offers there.
- **Denial of service.** Per-sender rate limits (§7.3), the size limits (§18), and per-peer timeouts and
  circuit breakers at the home keep one participant from exhausting another.

## 20. Conformance

Every target (S = SAJHA instance, A = SAJHA Net agent, L = reference library) runs this suite in CI.
A test marked with a feature applies only to targets that list it. The examples of §21 are test
vectors for SIG-01, SIG-12 and REC-01.

| Id | Targets | Asserts |
|---|---|---|
| NAME-01 | S A L | Configured names matching §5.2 are accepted; `_`, `.`, `:`, upper case, `--`, a leading digit or hyphen, a trailing hyphen and more than 32 characters are rejected. |
| NAME-02 | S A L | `10.20.4.17:3002` gives the prefix `10_20_4_17_3002`. |
| NAME-03 | S A L | `[2001:db8::7]:3002` gives `2001_0db8_0000_0000_0000_0000_0000_0007_3002`; no IPv6 prefix contains `__`; an IPv4-mapped address expands to eight groups. |
| NAME-04 | S A | Without a configured name, unspecified, loopback, `localhost` and link-local addresses are never used, and with no acceptable address the participant does not join and says why. |
| NAME-05 | S A L | A qualified name splits at the first `__`; a host tool named `a__b` round-trips. |
| NAME-06 | S A | A join, sync or signed request from a different key claiming a held name (holder alive, dead or left, certificate not revoked) gets `409 name_conflict` naming the holder; the newcomer appears in no member's list and no gossip. |
| NAME-07 | S A | A participant refused with `name_conflict` does not join, reports the error, and does not retry until its configuration or certificate changes; its local tools keep working. |
| NAME-08 | S | The CA refuses an enrollment token for a held name and names the holder; after the holder's certificate is revoked the name can be enrolled again. |
| NAME-09 | S A | A restart or certificate renewal with the same key is not a conflict. |
| CAP-01 | S A | `server/discover` carries `capabilities.extensions["io.sajha/net"]`, valid against `extension`. |
| CAP-02 | S A | A 2025-11-25 `initialize` result carries the same object under `capabilities.experimental`. |
| CAP-03 | S A | An unsigned discover may carry only `protocol_versions` and `endpoint`; a signed one carries the full object. |
| CAP-04 | S A L | The highest common version is used; a peer whose highest common version is below the minimum is refused with `unsupported_version` (HTTP 400 on `/sajhanet/`, `-32017` on MCP) listing supported versions. |
| CAP-05 | S A | A feature not listed answers `404` on its paths; a feature one side lacks is not used (no progress relayed without `progress` on both). |
| SIG-01 | S A L | The request of §21.1 verifies. |
| SIG-02 | S A | Missing `Signature`, `Signature-Input` or certificate header → 401 `signature_missing`. |
| SIG-03 | S A | One changed body byte → 401 `digest_mismatch`. |
| SIG-04 | S A | One changed covered header (each of them, in turn) → 401 `signature_invalid`. |
| SIG-05 | S A | `created` older than the maximum age, or more than 5 s ahead → 401 `signature_expired`. |
| SIG-06 | S A | The same (`keyid`, `nonce`) twice in the window → 401 `replay`; a request that fails verification does not consume its nonce. |
| SIG-07 | S A | A certificate from another CA → 401 `certificate_invalid`; from the right CA with another `O` → 403 `net_mismatch`. |
| SIG-08 | S A | A revoked serial → 403 `certificate_revoked`; a revoked instance name → 403 `instance_revoked`. |
| SIG-09 | S A L | `keyid` not the leaf thumbprint, or `alg` not matching the key → 401 `signature_invalid`; `hmac-sha256` and RSA algorithms are refused. |
| SIG-10 | S A | `Sajha-Net-From` not the certificate `CN` → 401 `from_mismatch`; `Sajha-Net-To` not the receiver → 421; the receiver's own name in the certificate → 409. |
| SIG-11 | S A | A request not covering a component §8.5 requires for it → 401 `signature_incomplete`. |
| SIG-12 | S A L | The response of §21.1 verifies against its request; an unsigned response, or one whose `"signature";req` value differs from the request's, is discarded. |
| SIG-13 | S A L | Ed25519 and ECDSA P-256 (raw `r‖s`) signatures both verify; a DER-encoded ECDSA signature does not. |
| SIG-14 | S A | In a streamed response, the final message's `response_signature` verifies; a changed result fails; progress notifications do not change the outcome. |
| SIG-15 | S A | `/sajhanet/` answers 404 when the net is disabled, and to `Sec-Fetch-Mode: navigate`; responses carry no CORS headers. |
| REC-01 | S A L | The key record of §21.3 verifies; reordering its members still verifies; changing any value fails. |
| REC-02 | S A L | A valid `key` signature does not verify when the same bytes are checked as a `member` record (domain separation). |
| GOS-01 | S A | A ping gets a signed ack; piggybacked updates are merged. |
| GOS-02 | S A | A ping-req pings the named member and reports `reachable`; an unknown target → 400 `unknown_member`; a URL in the request is ignored. |
| GOS-03 | S A | No direct or indirect ack → `suspect`; no refutation within the suspect timeout → `dead`. |
| GOS-04 | S A | A participant told it is `suspect` raises its incarnation and is `alive` everywhere within a few rounds. |
| GOS-05 | S A L | The merge rules of §9.4: each row of a table of (held, incoming) pairs gives the expected result. |
| GOS-06 | S A L | A member record signed by anyone but its subject, or whose `url` host is not in the subject's certificate, is dropped. |
| GOS-07 | S A | `left` without a subject-signed `leaving: true` record is ignored; a valid leave marks the member `left` at once. |
| GOS-08 | S A | A join sync through one seed returns the full list, including retained `dead` and `left` entries. |
| GOS-09 | S A | After a restart the incarnation exceeds the previous one, with persisted state lost and with the clock set back. |
| GOS-10 | S A | A revoked member's entries are dropped and its tools removed. |
| GOS-11 | S A | A dead member is still probed at the dead-probe rate and rejoins when it answers. |
| CAT-01 | S A | The catalog lists only tools exported to the requester; each is a valid MCP Tool with `_meta["io.sajha/net"]` valid against `tool_net_meta`. |
| CAT-02 | S A | `if_none_match` equal to the current hash → `unchanged: true` without `tools`; the hash is computed as §10.2 says. |
| CAT-03 | S A | A signed `tools/list` returns the same tools as the catalog endpoint. |
| CAT-04 | S | An unchanged digest causes no pull; a changed one causes exactly one; oversized catalogs and descriptions are capped and the peer flagged. |
| CAT-05 | S A (`visibility`) | Visibility lists, per key id, the tools that user may call; keys from another home get `not_home`. |
| KEY-01 | S A (`key_directory`) | A delta pull returns the responder's records with `version > since`, ascending, paged with `more` and `next_since`. |
| KEY-02 | S A L | Records whose `home_instance` is not the responder, or with a bad signature, or an older version, are ignored. |
| KEY-03 | S A L | The digest `root` is computed as §11.4; a mismatch triggers a pull from 0. |
| KEY-04 | S A | No record contains a raw key; `key_hash` is lowercase hex SHA-256 of the key; a deleted key reappears with `revoked_at` and a higher version. |
| KEY-05 | S A | Revoking a certificate serial discards the records it signed and re-pulls them. |
| BLK-01 | S A (`blocks`) | The blocks document is signed by its publisher, its version equals `digests.blocks`, and expired blocks are omitted. |
| REV-01 | S A L | A revocation list with a bad CA signature, another net or a lower version is ignored; any member serves the newest list it holds. |
| CA-01 | S (`ca`) | A valid token and CSR give a certificate with `O=<net>, CN=<instance>` and the CSR's key; the token is spent. |
| CA-02 | S (`ca`) | Reused, expired and wrong-name tokens, a CSR with a bad self-signature or a wrong subject → 403 `enrollment_refused`; enrollment over plain HTTP is refused. |
| CA-03 | S (`ca`) | Renewal signed with a valid certificate gives a new certificate for the same subject; another subject or a revoked certificate is refused. |
| CALL-01 | S A | A forwarded call with the headers of §15.2 runs as the user the key resolves to; the host audit holds the trace id and key id. |
| CALL-02 | S A | A key whose `home_instance` is not `Sajha-Net-From` → `-32013 key_not_from_home`. |
| CALL-03 | S A | Unknown, disabled, expired and revoked keys → `-32013` with the matching reason. |
| CALL-04 | S A | The home refuses to send a key over plain HTTP (`https_required`); the host refuses a key it receives on a hop it knows is not HTTPS. |
| CALL-05 | S A | A net-signed request also carrying `Authorization` or the ordinary API-key header → `-32013 ambiguous_credentials`; a request with `Sajha-Net-*` headers and a bad signature is never served. |
| CALL-06 | S A | Each step of §15.4 refuses with its code and reason, in order, with `data["io.sajha/net"]` complete. |
| CALL-07 | S A (`residency`) | Arguments of a class the host may not receive are refused at the home (`residency_arguments`); results the home may not receive are refused or redacted at the host (`residency_result`). |
| CALL-08 | S A | `hop_limit`, `loop` and `hop_inconsistent` are refused with `-32016`. |
| CALL-09 | S | A refusal reaches the home's caller as `isError: true` with `_meta["io.sajha/net"].refusal`. |
| CALL-10 | S A | The raw key appears in no log, audit record, trace attribute, metric label or stored row on either side. |
| CALL-11 | S A (`progress`, `cancellation`) | Progress reaches the caller; the caller's cancellation reaches the host. |
| CALL-12 | S A | On 2025-11-25, a session created by one participant cannot be used by another's signed requests. |
| CALL-13 | S A (`reexport`) | A re-exported call carries an assertion with `aud` = origin, no raw key, hop 2 and the visited list; an expired or replayed assertion → `-32013 assertion_invalid`. |
| ERR-01 | S A | Every `/sajhanet/` error is a signed `application/problem+json` body valid against `problem`. |
| LIM-01 | S A | Bodies and headers over §18 get 413; 32 updates and 1024 members are accepted. |

## 21. Examples

The examples use throwaway Ed25519 keys whose 32-byte private keys are the SHA-256 of the UTF-8 text
`sajha-net example: <label>`, with labels `acme-net CA`, `risk-eu` and `cust-na`. They are published
so the signatures can be checked; never use them for anything else.

The CA certificate (`O=acme-net, CN=acme-net CA`, serial 1):

```
MIIBJjCB2aADAgECAgEBMAUGAytlcDApMREwDwYDVQQKDAhhY21lLW5ldDEUMBIGA1UEAwwLYWNtZS1uZXQgQ0EwHhcNMjYxMDAxMDAwMDAwWhcNMzYxMDAxMDAwMDAwWjApMREwDwYDVQQKDAhhY21lLW5ldDEUMBIGA1UEAwwLYWNtZS1uZXQgQ0EwKjAFBgMrZXADIQAU74St0nczabbH0d6rF/LCbrZd+WHVAdsGiGlenT/aTqMmMCQwEgYDVR0TAQH/BAgwBgEB/wIBADAOBgNVHQ8BAf8EBAMCAQYwBQYDK2VwA0EAnDomu6qIswXIkXAgTBkvJISwwprAH5TvqXTB0DsUObmJfREpDIpmZAbddLzNY5aJEBpCUsVES9KW50koegP7Dg==
```

### 21.1 A signed tool call and its response

`alice@risk-eu` calls `cust-na__var_calc`; `risk-eu` forwards it to `cust-na`. Request:

```http
POST /mcp HTTP/1.1
Host: sajha-cust-na.example.internal
Content-Type: application/json
Accept: application/json, text/event-stream
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: var_calc
Sajha-Net-Version: 1
Sajha-Net-From: risk-eu
Sajha-Net-To: cust-na
Sajha-Net-Hop: 1
Sajha-Net-Visited: "risk-eu"
Sajha-Net-Api-Key: sja_U7ctcH-MN6JrIdIlX_PfCVXKc79Rmt58aTub2E7N97E
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
Content-Digest: sha-256=:GmWE8ztwdAgAKupEUE8ySGW/GDF1N4TRv6PSGmbSBl8=:
Sajha-Net-Certificate: :MIIBSTCB/KADAgECAgMaKzwwBQYDK2VwMCkxETAPBgNVBAoMCGFjbWUtbmV0MRQwEgYDVQQDDAthY21lLW5ldCBDQTAeFw0yNjEwMDEwMDAwMDBaFw0yNjEwMzEwMDAwMDBaMCUxETAPBgNVBAoMCGFjbWUtbmV0MRAwDgYDVQQDDAdyaXNrLWV1MCowBQYDK2VwAyEAIWvGipO7YbWU0Mxtr+alRgL4QiXNgPhYTBG2IOEdxKSjSzBJMAwGA1UdEwEB/wQCMAAwDgYDVR0PAQH/BAQDAgeAMCkGA1UdEQQiMCCCHnNhamhhLXJpc2stZXUuZXhhbXBsZS5pbnRlcm5hbDAFBgMrZXADQQCdjQWn60f/a+Co25hWcYkVpEm5gaan+h8jRb85AvE2F4vda21cPZJrjjZW6KpIhte1uVKZReH6ir3hYl6Xm7sJ:
Signature-Input: sajhanet=("@method" "@path" "@query" "content-type" "content-digest" "mcp-protocol-version" "mcp-method" "mcp-name" "sajha-net-version" "sajha-net-from" "sajha-net-to" "sajha-net-hop" "sajha-net-visited" "sajha-net-api-key" "traceparent");created=1791374400;nonce="q1QXbXk3WlNQ8n0Zr6dL4w";keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"
Signature: sajhanet=:u6DKXuhDJP0y5wZUtfor1OFkKiJGYiSnU7cye2bk/7muA78MOtt14IkKFG1YzShBgcmUyxSmJ+G5/vMLYZqrDw==:

{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"var_calc","arguments":{"portfolio":"EU-RATES","confidence":0.99,"horizon_days":10},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{"extensions":{"io.sajha/net":{"protocol_version":1}}},"traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01","io.sajha/net":{"home":"risk-eu","qualified_name":"cust-na__var_calc"}}}}
```

The body is the single line shown, with no trailing newline. Its signature base (what `risk-eu` signed;
never logged in practice, because it contains the key):

```
"@method": POST
"@path": /mcp
"@query": ?
"content-type": application/json
"content-digest": sha-256=:GmWE8ztwdAgAKupEUE8ySGW/GDF1N4TRv6PSGmbSBl8=:
"mcp-protocol-version": 2026-07-28
"mcp-method": tools/call
"mcp-name": var_calc
"sajha-net-version": 1
"sajha-net-from": risk-eu
"sajha-net-to": cust-na
"sajha-net-hop": 1
"sajha-net-visited": "risk-eu"
"sajha-net-api-key": sja_U7ctcH-MN6JrIdIlX_PfCVXKc79Rmt58aTub2E7N97E
"traceparent": 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
"@signature-params": ("@method" "@path" "@query" "content-type" "content-digest" "mcp-protocol-version" "mcp-method" "mcp-name" "sajha-net-version" "sajha-net-from" "sajha-net-to" "sajha-net-hop" "sajha-net-visited" "sajha-net-api-key" "traceparent");created=1791374400;nonce="q1QXbXk3WlNQ8n0Zr6dL4w";keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"
```

`cust-na` verifies the signature, finds the record of §21.3 by the key's hash
(`1db0e8728c95abfa10d2a7b40dabc56c240e72cc4c63d517815b22ac46f09ff4`), sees `home_instance: risk-eu` equal
to `Sajha-Net-From`, maps `alice@risk-eu`, applies its rules, runs the tool and answers:

```http
HTTP/1.1 200 OK
Content-Type: application/json
Sajha-Net-Version: 1
Sajha-Net-From: cust-na
Sajha-Net-To: risk-eu
Content-Digest: sha-256=:3cc/4zkToj3LIns5PQjmKsHtH56yWZ+r6ASgmPUwZ+8=:
Sajha-Net-Certificate: :<cust-na's certificate, issued by the same CA>:
Signature-Input: sajhanet=("@status" "content-type" "content-digest" "sajha-net-version" "sajha-net-from" "sajha-net-to" "signature";req;key="sajhanet");created=1791374401;keyid="TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I";alg="ed25519";tag="sajha-net-v1"
Signature: sajhanet=:h/kCVKW7iCnOE16yDGgN81Q61fRAO7iE3IDkgxE23t17BMPgKBP4l9kl42XQlWc3U7Y8/aAGzDsT+VQ+IAXLBw==:

{"jsonrpc":"2.0","id":7,"result":{"resultType":"complete","content":[{"type":"text","text":"{\"var\": 1843200.0, \"currency\": \"EUR\"}"}],"structuredContent":{"var":1843200.0,"currency":"EUR"},"isError":false,"_meta":{"io.sajha/net":{"instance":"cust-na","data_classes":{"results":["confidential"]}}}}}
```

Its signature base:

```
"@status": 200
"content-type": application/json
"content-digest": sha-256=:3cc/4zkToj3LIns5PQjmKsHtH56yWZ+r6ASgmPUwZ+8=:
"sajha-net-version": 1
"sajha-net-from": cust-na
"sajha-net-to": risk-eu
"signature";req;key="sajhanet": :u6DKXuhDJP0y5wZUtfor1OFkKiJGYiSnU7cye2bk/7muA78MOtt14IkKFG1YzShBgcmUyxSmJ+G5/vMLYZqrDw==:
"@signature-params": ("@status" "content-type" "content-digest" "sajha-net-version" "sajha-net-from" "sajha-net-to" "signature";req;key="sajhanet");created=1791374401;keyid="TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I";alg="ed25519";tag="sajha-net-v1"
```

A real 2026-07-28 result also carries the server-info `_meta` and caching fields; they are left out
here for length, and would be covered by the digest like everything else in the body.

### 21.2 A gossip exchange

`risk-eu` pings `cust-na`, carrying news that `treasury-na` is suspect. Headers are signed as in §8.5
(covering `@method`, `@path`, `@query`, `content-type`, `content-digest`, `sajha-net-version`,
`sajha-net-from`, `sajha-net-to`); signatures and certificates inside the body are elided as `…`.

```http
POST /sajhanet/v1/gossip/ping HTTP/1.1
Host: sajha-cust-na.example.internal
Content-Type: application/json
Sajha-Net-Version: 1
Sajha-Net-From: risk-eu
Sajha-Net-To: cust-na
Content-Digest: sha-256=:…:
Sajha-Net-Certificate: :…:
Signature-Input: sajhanet=("@method" "@path" "@query" "content-type" "content-digest" "sajha-net-version" "sajha-net-from" "sajha-net-to");created=1791374410;nonce="mG3s0QXf2b8Yk1pLr7Hc9A";keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"
Signature: sajhanet=:…:

{"type": "ping", "seq": 1187, "updates": [
  {"record": {"type": "member", "net": "acme-net", "name": "treasury-na",
              "url": "https://sajha-treasury-na.example.internal", "mcp_path": "/mcp",
              "region": "us-east", "labels": {"domain": "treasury", "jurisdiction": "US"},
              "kind": "sajha", "protocol_versions": [1], "features": ["gossip", "catalog", "key_directory", "key_verification"],
              "user_identity": ["api_key"], "incarnation": 1791360000000, "seq": 2,
              "digests": {"catalog": "sha256:a91e44f0", "keys": 17, "blocks": 0, "revocations": 7},
              "leaving": false, "issued_at": "2026-10-07T08:41:10Z"},
   "signature": {"alg": "ed25519", "keyid": "…", "sig": "…"},
   "state": "suspect", "reported_by": "risk-eu", "reported_at": "2026-10-07T12:00:09Z"}
]}
```

`cust-na` merges the entry (same incarnation, `suspect` outranks `alive`) and acks with its own
re-signed record, whose key-directory version moved from 41 to 42:

```json
{"type": "ack", "seq": 1187, "updates": [
  {"record": {"type": "member", "net": "acme-net", "name": "cust-na",
              "url": "https://sajha-cust-na.example.internal", "mcp_path": "/mcp",
              "region": "us-east", "labels": {"domain": "customer", "jurisdiction": "US"},
              "kind": "sajha", "protocol_versions": [1],
              "features": ["gossip", "catalog", "visibility", "key_directory", "key_verification", "blocks"],
              "user_identity": ["api_key"], "incarnation": 1791371234567, "seq": 9,
              "digests": {"catalog": "sha256:0c55e1b7", "keys": 42, "blocks": 1, "revocations": 7},
              "leaving": false, "issued_at": "2026-10-07T12:00:02Z"},
   "signature": {"alg": "ed25519", "keyid": "TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I", "sig": "…"},
   "state": "alive"}
]}
```

The ack response is signed as in §8.8. `risk-eu` sees `keys` at 42 for `cust-na`, above the 41 it
holds, and calls `POST /sajhanet/v1/keys` on `cust-na` with `{"since": 41}`. If `treasury-na` hears
of its suspicion, it re-signs with a higher incarnation and is `alive` again everywhere.

### 21.3 A key record

The record of the key used in §21.1, signed by `risk-eu`:

```json
{
  "type": "key",
  "key_id": "0b6f3c1e-8a4d-4f7e-9c21-5d3e7a9b2f10",
  "key_prefix": "sja_U7ctcH-M...",
  "name": "alice laptop",
  "key_hash": "1db0e8728c95abfa10d2a7b40dabc56c240e72cc4c63d517815b22ac46f09ff4",
  "home_instance": "risk-eu",
  "owner": { "user_id": "7d2a9e44-1c3b-4b8e-a6f0-2e9d8c7b5a31", "user_name": "alice",
             "display_name": "Alice Martin", "roles": ["analyst"] },
  "enabled": true,
  "expires_at": "2027-04-01T00:00:00Z",
  "revoked_at": null,
  "tool_access_mode": "allowlist",
  "tool_access_list": ["var_calc", "stress_test"],
  "persistent": false,
  "version": 42,
  "updated_at": "2026-10-07T11:58:03Z",
  "signature": { "alg": "ed25519", "keyid": "_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ",
                 "sig": "qShDuzikCPsmi6TuBlU_g5btDfV-tqcIBYh4ahgzkBNxMJ9dWC4vwTtE3gu6Bvsh3lVx7XDCc0LNagEik70oBA" }
}
```

The signing input is the ASCII `sajha-net-v1:key:` followed by the JCS form of the record without
`signature`:

```
{"enabled":true,"expires_at":"2027-04-01T00:00:00Z","home_instance":"risk-eu","key_hash":"1db0e8728c95abfa10d2a7b40dabc56c240e72cc4c63d517815b22ac46f09ff4","key_id":"0b6f3c1e-8a4d-4f7e-9c21-5d3e7a9b2f10","key_prefix":"sja_U7ctcH-M...","name":"alice laptop","owner":{"display_name":"Alice Martin","roles":["analyst"],"user_id":"7d2a9e44-1c3b-4b8e-a6f0-2e9d8c7b5a31","user_name":"alice"},"persistent":false,"revoked_at":null,"tool_access_list":["var_calc","stress_test"],"tool_access_mode":"allowlist","type":"key","updated_at":"2026-10-07T11:58:03Z","version":42}
```

## 22. Decisions made in this spec

The design leaves these open or states them loosely; this specification decides them as follows.

1. **Versioned path.** Endpoints live under `/sajhanet/v1/`, not directly under `/sajhanet/`, so a
   future incompatible version can be served alongside (§4).
2. **2025-11-25 advertisement goes in `capabilities.experimental`.** That era's capabilities have no
   `extensions` member, and SAJHA negotiates the tasks extension only on 2026-07-28 (§6.1).
3. **`snake_case`** for every field of the extension, following the design's `_meta` example.
4. **Covered components** exclude `@authority` and `@scheme` (rewritten by TLS-terminating proxies);
   `Sajha-Net-To` binds the recipient instead (§8.5).
5. **Ed25519 and ECDSA P-256 both MUST verify**; Ed25519 is the one every signer must be able to use
   (§8.2). ECDSA signatures are raw `r‖s`.
6. **Certificate header** is an RFC 8941 list of DER byte sequences, leaf first, not covered by the
   signature (bound by `keyid`, the leaf's SHA-256 thumbprint) (§8.3).
7. **Clock allowance** of 5 s into the future; maximum age capped at 300 s; nonces recorded only after
   a request verifies (§8.7).
8. **Responses are bound to requests** by covering `"signature";req`; streamed responses sign their
   final message with a JCS signature carrying the request nonce (§8.8, §8.9).
9. **Record signatures** use a domain-separated prefix (`sajha-net-v1:<type>:`) over JCS, with a small
   `{alg, keyid, sig}` object rather than JWS (§8.10).
10. **Member records are signed by their subjects** and carry a `seq` within an incarnation, so relays
    cannot alter a member's URL or digests and digest changes order correctly (§9.1, §9.4).
11. **`left` needs the subject's signature** (`leaving: true`); state precedence at equal incarnation is
    `alive < suspect < dead < left` (§9.4).
12. **Incarnation** is `max(now_ms, last + 1)` in milliseconds, covering both a lost store and a clock
    set back (§9.3).
13. **Catalog digest** in gossip is one opaque value per participant that changes when any peer's view
    may change; each pull returns a peer-specific `hash` usable with `if_none_match` (§10).
14. **Catalogs travel on `/sajhanet/v1/catalog`**, and a signed `tools/list` must return the same set
    (§10.4).
15. **Visibility endpoint** (§10.5), so a home can hide proxies a user has no account for; the design
    asks for that hiding but gives the home no way to know.
16. **Key records add `user_name`, `persistent` and `type`**; a deleted key becomes a revoked record;
    one version counter per home; a digest `root` for anti-entropy (§11).
17. **Blocks** are pulled from their publisher when `digests.blocks` increases; reasons may be
    withheld (§12).
18. **Revocation list** is CA-signed, versioned, served by every member, and revokes by instance name
    or certificate serial (§13).
19. **Enrollment** is unsigned and token-authenticated, with one refusal reason for every failure;
    renewal is signed and RECOMMENDS a new key (§14).
20. **Forwarded API key header** is `Sajha-Net-Api-Key`; a net-signed request may not also carry
    `Authorization` or `X-API-Key` (§15.2).
21. **Re-export identity** is a home-signed assertion addressed to the tool's `origin`, forwarded
    unchanged by intermediaries; raw keys are never sent past hop 1 (§15.5, §16).
22. **Error codes** `-32011` to `-32019` with `data["io.sajha/net"]`, in SAJHA's implementation-defined
    range; between participants refusals are JSON-RPC errors, and the home shows its caller an
    `isError` result (§15.7, §17).
23. **Manual mode** uses self-signed certificates with pinned thumbprints and otherwise the same
    protocol (§8.11).
24. **Name syntax.** Configured instance names are lowercase, start with a letter and have at most 32
    characters; net names at most 63 (§5).
25. **Hop maximum** of 8 regardless of configuration (§16).

## 23. References

- RFC 2119, RFC 8174: requirement levels.
- RFC 3339: timestamps. RFC 4648: base64 and base64url. RFC 5952: IPv6 text form.
- RFC 5280: X.509 certificates. RFC 2986: PKCS #10 certificate requests. RFC 8032: Ed25519.
- RFC 7493: I-JSON. RFC 8259: JSON. RFC 8785: JSON Canonicalization Scheme (JCS).
- RFC 8941: Structured Field Values for HTTP.
- RFC 9421: HTTP Message Signatures. RFC 9530: Digest Fields.
- RFC 9457: Problem Details for HTTP APIs.
- RFC 8693: OAuth 2.0 Token Exchange (the reserved `token_exchange` resolver).
- W3C Trace Context (`traceparent`, `tracestate`).
- JSON Schema 2020-12.
- Das, Gupta and Motivala, *SWIM: Scalable Weakly-consistent Infection-style Process Group
  Membership Protocol*, 2002.
- The MCP specification, eras 2025-11-25 and 2026-07-28, as SAJHA implements them:
  [MCP Protocol Guide](MCP%20Protocol%20Guide.md).
- The design this specifies: [SAJHA Net](../architecture/SAJHA%20Net.md).
