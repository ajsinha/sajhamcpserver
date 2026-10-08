# Tutorial 39: Console Single Sign-On

The console can sign people in with an OpenID Connect identity provider, alongside password sign-in and
API keys. Instances that are clients of the same provider share one sign-in: sign in once, and the next
instance's console lets you in without a password. This tutorial runs it offline on the
[local test lab](TUTORIAL_29_local_test_lab.md) with a fake provider that ships with the lab, then lists
what to change for a real one. The rules are in the [Security Model](../security/Security%20Model.md)
("Console single sign-on"); every key is in the
[Configuration Reference](../getting-started/Configuration%20Reference.md).

## What you'll learn

- What `auth.sso.*` configures, and how SAJHA validates a sign-in
- How a provider's user becomes a SAJHA user: linking, creating, mapping roles
- What "several instances, one sign-in" means, and what signing out does and does not end
- What to set for a real provider

## Prerequisites

- The local test lab ([Tutorial 29](TUTORIAL_29_local_test_lab.md)), freshly reset
- A browser

## Steps

### 1. Start the fake provider

```bash
python deployment/local-lab/fake_idp.py
```

```text
Lab identity provider on http://127.0.0.1:3010 (client_id sajha-lab); Ctrl+C stops it
```

[`fake_idp.py`](../../deployment/local-lab/fake_idp.py) implements the authorization code flow with
PKCE: an OpenID Connect discovery document, an authorization form that asks for a
user name and groups (no password: it believes what you type), a token endpoint that signs ID tokens with
an RSA key it made at start (RS256, published at `/jwks`), and an end-session endpoint. It remembers who
signed in with its own cookie. Never use it outside a lab.

### 2. Point the three instances at it

Create `run/local.yml` (all three instances):

```yaml
auth:
  sso:
    enabled: true
    issuer: http://127.0.0.1:3010
    client_id: sajha-lab
    label: the lab identity provider
    roles_claim: groups
    role_map: ["sajha-admins=admin", "staff=user"]
    auto_provision: true
```

and restart the lab (`lab.sh stop`, `lab.sh start`). SAJHA requires `https` for the provider's endpoints
except on `localhost` and `127.0.0.1`, which is what lets the fake provider run on plain HTTP. This
provider needs no client secret; for one that does, the secret comes from `SAJHA_AUTH_SSO_CLIENT_SECRET`
in the environment (in the lab, a `lab_env:` entry), never from a configuration file. Check:

```bash
curl -s http://127.0.0.1:3002/api/auth/sso
```

```text
{"enabled":true,"label":"the lab identity provider","login_url":"/auth/sso/login","auto_redirect":false}
```

### 3. Sign in

Open http://127.0.0.1:3002/login. Above the password form is **Sign in with the lab identity provider**.
Click it: SAJHA reads the provider's discovery document, keeps a random state, nonce and PKCE verifier in
its state store for ten minutes, binds them to this browser with the `sajha_sso` cookie, and sends you to
the provider. Enter `alice` with groups `staff` and sign in.

Back at `/auth/sso/callback`, SAJHA took the state (once), exchanged the code with the verifier, and
validated the ID token: the signature by a key of the provider's key set (`none` and HMAC are refused),
`iss`, `aud`, `exp`, `iat`, `sub`, `nonce` and `at_hash`. There is no `alice` on `risk-eu`, and
`auto_provision` is on, so it created one with the role mapped from `staff` (`user`), linked to the
provider's subject, and started an ordinary console session. You land on the dashboard as Alice.

### 4. One sign-in for the others

Open http://127.0.0.2:3003/login and click the same button. There is no form this time: the provider
still knows you, so it answers at once, and `cust-na` signs you in as its own `alice` (created the same
way). Do the same on http://127.0.0.3:3004. Each instance maps the person to **its own** user; SAJHA
Net keeps users per instance. With `auth.sso.auto_redirect: true`, `/login` goes straight to the
provider (`/login?local=1` still shows the password form).

### 5. Link an existing account, and roles

In a private browser window (the provider does not know you there), sign in to `treasury-eu` through the
provider as `testadmin` with groups `sajha-admins`. `treasury-eu` already has a `testadmin` (from its users file), and
`auth.sso.link_existing` (on by default) links it to the provider's subject on first sign-in (audited
`user.sso_linked`). With `link_existing` on, whoever the provider says is `testadmin` becomes the local
`testadmin`: turn it off, or link accounts deliberately, when people can choose their own names at the
provider. `role_map` maps `sajha-admins` to `admin` for created users; `auth.sso.sync_roles: true` would
also replace an existing user's roles at every sign-in (never for users in the users file, whose file
wins), and `auth.sso.require_role: true` refuses a sign-in that maps to no role.

### 6. Signing out

Sign out on `risk-eu` (user menu, or `/logout`). SAJHA revokes its token and, because the session came
from single sign-on, sends you to the provider's end-session endpoint (`auth.sso.idp_logout`, on by
default), which ends the provider's session and returns you to `risk-eu`'s login page. Now open
http://127.0.0.2:3003/dashboard: you are still signed in there. There is no back-channel sign-out: a
session another instance already issued lasts until it expires (`auth.jwt.expiry_minutes`) or is
revoked there. Signing in again anywhere now shows the provider's form, because its session ended.

### 7. Stop

Stop the provider with Ctrl+C, then remove `run/local.yml` and restart the lab (or `lab.sh reset`).

### 8. With a real provider

For Keycloak, Entra ID, Okta, Auth0 or any OpenID Connect provider:

- register one client (confidential, authorization code with PKCE) and one redirect URI per instance:
  `<instance URL>/auth/sso/callback` (or set `auth.sso.redirect_uri`; behind a proxy, `mcp.auth.public_url`
  sets the origin);
- set `auth.sso.issuer` to the provider's issuer URL (its discovery document must name the same issuer,
  and its endpoints must be https) and `auth.sso.client_id`, and put the secret in
  `SAJHA_AUTH_SSO_CLIENT_SECRET`;
- choose the claim that names the SAJHA user (`auth.sso.user_claim`, default `preferred_username`; with
  `email`, an unverified address is refused), and the roles claim and map (`groups`, or a dotted name such
  as `realm_access.roles`);
- decide `auto_provision` (default off) and `link_existing` (default on) for your provider.

This tutorial's flow was exercised end to end against the fake provider: discovery, PKCE, ID token
validation, user creation with a mapped role, linking of an existing account, the shared sign-in on three
instances and provider sign-out. A real provider was not part of the run.

## What you learned

- `auth.sso.*` adds "Sign in with ..." to the login page, beside the other sign-ins; secrets stay in the
  environment
- SAJHA validates the ID token strictly and maps the person to a local user by subject, then by name
  (link) or by creating one, with roles from a claim
- Instances using one provider share a sign-in, each with its own user; signing out ends the provider's
  session but not other instances' sessions

## Next

- The SAJHA Net design these tutorials explored: [SAJHA Net](../architecture/SAJHA%20Net.md)
- This is the last tutorial; the [documentation index](../README.md) lists every guide

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
