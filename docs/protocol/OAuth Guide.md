# OAuth Guide

How to protect SAJHA's MCP endpoints with OAuth 2.1, following the MCP authorization
specification (the same rules for 2026-07-28 and 2025-11-25 clients). This guide is
the setup manual. The requirement-by-requirement description and the security
decisions are in [MCP 2026-07-28 Compliance §4.1](MCP%202026-07-28%20Compliance.md);
every key is listed in the [Configuration Reference](../getting-started/Configuration%20Reference.md).

What OAuth here is **not**: it is not single sign-on for the SAJHA web UI, and SAJHA is
not an OpenID Connect provider (it issues no ID tokens, and
`/.well-known/openid-configuration` is 404). It controls who may call `/mcp`.

---

## 1. Concepts in one paragraph

An MCP client that receives **401** from `/mcp` reads the `resource_metadata` URL in
the `WWW-Authenticate` header and fetches SAJHA's **Protected Resource Metadata**
(RFC 9728). That document names the **authorization server**. The client then runs the
authorization-code flow with **PKCE** (S256) and a **resource indicator**
(RFC 8707, the URI of SAJHA's `/mcp`), receives a JWT **access token** whose audience is
that URI, and sends it as `Authorization: Bearer …` on every MCP request. SAJHA checks
signature, issuer, audience, expiry and **scope**. The terms are defined in the
[Glossary](../../GLOSSARY.md).

---

## 2. Choose a mode

| `mcp.auth.mode` | Anonymous calls | OAuth tokens | Discovery documents |
|---|---|---|---|
| `"off"` (default) | allowed | not checked | 404, so clients see "no OAuth" |
| `optional` | allowed | validated; an invalid token gets 401 `invalid_token` | served |
| `required` | **401** with a challenge | validated | served |

Quote `"off"` in YAML: bare `off` is a boolean. Environment override:
`SAJHA_MCP_AUTH_MODE=required`.

In every mode, SAJHA's own credentials keep working on `/mcp`: an `X-API-Key`
(`sja_…` keys), a SAJHA login JWT, or the `sajha_token` cookie. They are not
scope-checked. (Note: per-role tool filtering is not active on MCP endpoints in this
release; see the [Security Model](../security/Security%20Model.md).) OAuth access
tokens, in turn, are accepted **only** on the MCP endpoints (`/mcp`, `/api/mcp`,
`GET /mcp/sse`, `POST /mcp/message`, `DELETE /mcp`), never on the REST API. The
WebSocket transport (`/mcp/ws`) accepts SAJHA JWTs and API keys only.

A sensible rollout: `optional` first (nothing breaks, OAuth clients can start using
tokens), then `required`.

---

## 3. Set the public URL

```yaml
mcp:
  auth:
    public_url: https://mcp.example.com
```

The token audience (`<public_url>/mcp`) and the built-in issuer derive from it. Left
empty, SAJHA uses each request's `Host`, which is fine on a laptop and wrong behind a
proxy or with several host names. Set it in production.

---

## 4. Option A: the built-in authorization server

`mcp.auth.authorization_server: builtin` (the default). SAJHA itself issues tokens,
and the people who sign in are SAJHA users (the same accounts as the web UI).

```yaml
mcp:
  auth:
    mode: required
    authorization_server: builtin
    public_url: https://mcp.example.com
```

This serves:

| Endpoint | Purpose |
|---|---|
| `/.well-known/oauth-protected-resource` (also `/mcp` and `/api/mcp` suffixes) | PRM: resource URI, authorization server, scopes |
| `/.well-known/oauth-authorization-server` | RFC 8414 metadata |
| `/oauth/authorize` | Consent page. The user is taken from the SAJHA session cookie or signs in on the page. |
| `/oauth/token` | Code and refresh-token exchange |
| `/oauth/jwks` | Public signing key |
| `/oauth/register` | Only with dynamic client registration enabled |

### Registering clients

A client must be known before it can be sent to `/oauth/authorize`. Three ways, in
order of preference:

1. **Client ID Metadata Documents (CIMD), on by default.** The client's `client_id` is
   an `https://` URL that serves its own metadata (name, redirect URIs). SAJHA fetches
   and validates it, with SSRF guards. Nothing to configure. Only public (PKCE-only)
   clients. For local development with an `http://localhost` client ID, set
   `mcp.auth.builtin.cimd.allow_localhost: true`.
2. **Pre-registered clients**, for clients with a fixed ID:

   ```yaml
   mcp:
     auth:
       builtin:
         clients:
           - client_id: my-agent
             client_name: My Agent
             redirect_uris: ["http://127.0.0.1:8765/callback"]
             client_secret: ${MY_AGENT_SECRET:}   # omit for a public client
   ```

   Or as JSON in `SAJHA_MCP_AUTH_BUILTIN_CLIENTS`. Redirect URIs are matched exactly
   and must be https, loopback http, or a reverse-domain native scheme
   (`com.example.app:/cb`); an entry with an invalid one is ignored with a warning.
3. **Dynamic Client Registration** (RFC 7591): `mcp.auth.builtin.dynamic_client_registration: true`.
   Deprecated in MCP 2026-07-28. Registrations are kept in the state store (`state.backend`),
   which is process memory by default.

### Scopes and refresh tokens

- `mcp:read` lets a client list and read; `mcp:tools` lets it call tools; `mcp`
  implies both. A token missing the needed scope gets **403** `insufficient_scope`.
- A refresh token is issued only when the client asks for `offline_access` (policy
  `mcp.auth.builtin.refresh_tokens`: `offline_access` | `always` | `never`). Refresh
  tokens rotate on every use; reusing an old one revokes the chain.
- Lifetimes: `access_token_ttl_seconds` (default 15 minutes), `refresh_token_ttl_seconds`,
  `code_ttl_seconds`.

### The signing key

Generated on first use (RSA-2048, mode 0600) at `<data.dir>/oauth/signing_key.pem`, or
`mcp.auth.builtin.signing_key_path`. It is git-ignored; never commit it. Every
instance that issues or validates tokens must use the same key: share the data directory,
or give every host the PEM in `mcp.auth.builtin.signing_key_pem` (env
`SAJHA_MCP_AUTH_BUILTIN_SIGNING_KEY_PEM`).

### Operational limits

Pending consents, authorization codes, refresh tokens and DCR registrations are held
in the state store. With the default `state.backend: memory` they are per process: a
restart signs OAuth clients out (access tokens stay valid until they expire, because the
key persists). With `redis` or `database`, every worker shares them, so a code issued by one
worker is redeemed at another, and they survive a restart. See
[Scaling and State](../architecture/Scaling%20and%20State.md). Access tokens cannot be revoked before they expire.

---

## 5. Option B: an external identity provider

Point SAJHA at an issuer you already run (Keycloak, Okta, Entra ID, Auth0, ...). SAJHA
then only **validates** tokens; it serves the PRM document naming that issuer, and the
built-in `/oauth/*` and authorization-server metadata endpoints are 404.

```yaml
mcp:
  auth:
    mode: required
    authorization_server: https://login.example.com/realms/mcp   # exact issuer string
    public_url: https://mcp.example.com
    accepted_audiences: ""        # extra aud values, e.g. an Entra application ID URI
    external:
      user_claim: sub             # claim matched to a SAJHA user ID
```

What SAJHA needs from the identity provider:

| Requirement | Detail |
|---|---|
| Discovery | RFC 8414 metadata or OpenID discovery at the issuer, with an `issuer` equal to the configured string and a `jwks_uri`. The JWKS is cached for `jwks_cache_seconds`, and refetched (at most every 30 s) when an unknown `kid` arrives. |
| JWT access tokens | Signed with an asymmetric algorithm (RS*, PS*, ES*). `none` and HS* are refused. Opaque tokens are not supported (no introspection). |
| Audience | `aud` must contain `<public_url>/mcp` (or `/api/mcp`), or a value in `accepted_audiences`. Configure an audience mapper or API identifier in the IdP. |
| Scopes | `mcp:read` / `mcp:tools` (or `mcp`) in the `scope` or `scp` claim. |
| Identity | The `user_claim` value is matched to a SAJHA user ID, which becomes the caller's identity. An unmatched identity gets the least-privilege `api_consumer` role. Use a claim the IdP controls. |

The client itself registers with your IdP as usual; SAJHA is not involved in that step.

---

## 6. Check that it works

```bash
# PRM: should name your authorization server
curl -s https://mcp.example.com/.well-known/oauth-protected-resource/mcp

# required mode: an anonymous call gets 401 with the challenge
curl -si https://mcp.example.com/mcp -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  | grep -i www-authenticate
```

End to end, the official MCP Python SDK's `OAuthClientProvider` completes the flow
against the built-in server in both protocol eras, and the conformance suite's
`authorization` scenarios pass; the commands are in
[MCP 2026-07-28 Compliance §5](MCP%202026-07-28%20Compliance.md). The tests are in
`tests/test_mcp_auth.py`.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
