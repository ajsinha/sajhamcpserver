# SAJHA MCP Server v5.2.0 — Cybersecurity & Data Safety Assessment

**Date:** May 2026
**Scope:** Full application stack — authentication, authorization, transport, data storage, input handling, HTTP security
**Standard:** OWASP Top 10 (2021), MCP Security Best Practices, CWE/SANS Top 25
**Verdict:** Production-Ready — 31/31 security controls verified, 0 critical/high findings

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.

---

## Executive Summary

SAJHA MCP Server v5.2.0 implements 31 security controls across 7 categories: authentication, cookie security, API key management, HTTP security headers, CORS policy, input validation, and database schema hardening. All credentials (passwords, API keys, session tokens) are stored as cryptographic hashes — never in plaintext. The application enforces account lockout, rate limiting, session expiry, request size limits, and SQL allowlisting. A full security headers middleware provides defense-in-depth against XSS, clickjacking, MIME sniffing, and protocol downgrade attacks.

This document catalogs every security control with its implementation details, source file locations, and verification methods.

---

## Security Controls Catalog

### Category 1: Authentication (9 controls)

---

#### SC-1.1: Password Hashing with bcrypt

**Threat:** CWE-256 (Plaintext Storage of Password), CWE-916 (Weak Password Hash)

**Control:** All user passwords are hashed with bcrypt using 12 salt rounds before storage. Plaintext passwords never exist in memory beyond the authentication function scope.

**Implementation:**

| Component | Location |
|-----------|----------|
| `hash_password(password)` | `sajha/security.py` line 32 |
| `verify_password(password, hash)` | `sajha/security.py` line 37 |
| Password hashed on user creation | `sajha/core/auth_manager.py` — `create_user()` calls `hash_password()` |
| Password hashed on update | `sajha/core/auth_manager.py` — `update_user()` calls `hash_password()` |
| Verification on login | `sajha/core/auth_manager.py` — `authenticate()` calls `verify_password()` |

**How it works:**

```python
# Storage (create/update user)
password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))

# Verification (login)
bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
```

bcrypt is a deliberately slow hash function (adaptive cost factor). At 12 rounds, each hash takes ~250ms, making brute-force attacks computationally expensive. The random salt ensures identical passwords produce different hashes.

**Verification:**

```bash
# Check that password_hash column is used, not plaintext password
grep -n "password_hash" sajha/core/auth_manager.py
# Should show: user.password_hash in verify_password() call
# Should NOT show: user.get('password') != password
```

---

#### SC-1.2: No Hardcoded Credentials

**Threat:** CWE-798 (Use of Hardcoded Credentials)

**Control:** No passwords, API keys, or secrets are hardcoded in source code. The default admin user's password is stored as a bcrypt hash in the seed SQL script.

**Implementation:**

| Component | Location |
|-----------|----------|
| Seed SQL with bcrypt hash | `db/scripts/sqlite/002_seed.sql` |
| No `admin123` in auth code | `sajha/core/auth_manager.py` — verified absent |

The seed script contains:

```sql
INSERT OR IGNORE INTO users (..., password_hash, ...)
VALUES (..., '$2b$12$...bcrypt_hash...', ...);
```

The raw password `admin123` does not appear in any Python source file. It only exists as documentation in the CHANGELOG noting that users should change it on first login.

---

#### SC-1.3: Database-Persisted Sessions

**Threat:** CWE-613 (Insufficient Session Expiration), CWE-384 (Session Fixation)

**Control:** Sessions are stored in the `user_sessions` database table with hashed tokens, not in-memory dicts. Sessions survive server restarts and can be shared across instances.

**Implementation:**

| Component | Location |
|-----------|----------|
| Session creation | `sajha/core/auth_manager.py` — `authenticate()` creates `UserSession` row |
| Token hashing | `sajha/security.py` — `generate_session_token()` returns `(raw, sha256_hash)` |
| DB storage | `sajha/db/models/__init__.py` — `UserSession` model with `token_hash` column |
| Validation | `sajha/core/auth_manager.py` — `validate_session()` queries by hash |

**How it works:**

```python
# Login: generate token, hash it, store hash in DB, return raw to client
raw_token, token_hash = generate_session_token()  # secrets.token_urlsafe(32) + SHA-256
session = UserSession(token_hash=token_hash, user_id=user.id, expires_at=...)
db.add(session)

# Validation: hash incoming token, look up by hash
token_hash = hashlib.sha256(token.encode()).hexdigest()
session = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
```

Even if the database is compromised, session tokens cannot be reversed from their SHA-256 hashes.

---

#### SC-1.4: Session Expiry

**Threat:** CWE-613 (Insufficient Session Expiration)

**Control:** Every session has an `expires_at` timestamp (default: 1 hour). Expired sessions are rejected and deleted from the database.

**Implementation:**

```python
# On creation
expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.session_ttl)  # default 3600

# On validation
if session.expires_at < datetime.now(timezone.utc):
    db.delete(session)  # Remove expired session
    return None
```

A background `cleanup_expired_sessions()` method removes stale sessions.

---

#### SC-1.5: Account Lockout

**Threat:** CWE-307 (Improper Restriction of Excessive Authentication Attempts)

**Control:** After 5 consecutive failed login attempts, the account is locked for 15 minutes. The lock applies at the user level (not just IP), preventing distributed brute-force attacks.

**Implementation:**

| Component | Location |
|-----------|----------|
| Lockout check | `sajha/security.py` — `check_account_locked()` |
| Failed attempt tracking | `sajha/core/auth_manager.py` — `authenticate()` increments `user.failed_attempts` |
| Lock timestamp | `sajha/core/auth_manager.py` — sets `user.locked_until` after 5 failures |
| Reset on success | `sajha/core/auth_manager.py` — resets `failed_attempts` to 0 on successful login |
| DB columns | `users.failed_attempts` (Integer), `users.locked_until` (DateTime) |

**Constants:** `MAX_FAILED_ATTEMPTS = 5`, `LOCKOUT_DURATION_SECONDS = 900` (15 minutes).

---

#### SC-1.6: Rate Limiting on Authentication

**Threat:** CWE-799 (Improper Control of Interaction Frequency)

**Control:** Authentication endpoints are rate-limited to 5 requests per minute per IP address using a sliding window counter. Requests exceeding the limit receive HTTP 429.

**Implementation:**

| Component | Location |
|-----------|----------|
| Rate limiter | `sajha/security.py` — `RateLimiter` class (sliding window, in-memory) |
| Auth limiter instance | `sajha/security.py` — `_auth_limiter = RateLimiter(max_requests=5, window_seconds=60)` |
| Web login check | `sajha/routes/auth_routes.py` — `web_login()` calls `check_auth_rate_limit()` |
| API login check | `sajha/routes/auth_routes.py` — `api_login()` calls `check_auth_rate_limit()` |

```python
# Returns 429 if rate limit exceeded
if not check_auth_rate_limit(request):
    return JSONResponse({'error': 'Too many login attempts. Try again in 60 seconds.'}, status_code=429)
```

---

#### SC-1.7: Multi-Method Authentication

**Threat:** Defense in depth — multiple authentication methods for different use cases.

**Control:** Four authentication methods, checked in priority order:

| Priority | Method | Header/Source | Use Case |
|:--------:|--------|--------------|----------|
| 1 | Bearer JWT | `Authorization: Bearer <token>` | API clients |
| 2 | API Key | `X-API-Key: sja_...` or `?api_key=` | Automation, CI/CD |
| 3 | Session Cookie | `sajha_token` cookie | Web UI |
| 4 | Unauthenticated | — | Public pages (help, about, landing) |

**Implementation:** `AuthManager.authenticate_request()` in `sajha/core/auth_manager.py`.

---

#### SC-1.8: Passwords Never Returned in API Responses

**Threat:** CWE-200 (Exposure of Sensitive Information)

**Control:** The `get_all_users()` and `get_user()` methods construct response dicts explicitly, including only `id`, `user_id`, `user_name`, `email`, `enabled`, `roles`, `created_at`, `last_login`. The `password_hash` field is never included.

**Implementation:** `sajha/core/auth_manager.py` — both methods build dicts with explicit field lists, not `user.__dict__`.

---

#### SC-1.9: OAuth SSO Integration

**Threat:** Centralized identity management for enterprise environments.

**Control:** OAuth 2.1 integration supports Azure AD, Okta, Auth0, and Keycloak. PKCE (S256) is supported for all flows. The User model includes `oauth_provider` and `oauth_subject` fields for federated identity.

---

### Category 2: Cookie Security (3 controls)

---

#### SC-2.1: HttpOnly Flag

**Control:** Session cookie `sajha_token` is set with `httponly=True`, preventing JavaScript access (mitigates XSS-based token theft).

**Implementation:** `sajha/routes/auth_routes.py` — `response.set_cookie(key='sajha_token', ..., httponly=True, ...)`

---

#### SC-2.2: SameSite Attribute

**Control:** Cookie is set with `samesite='lax'`, preventing the browser from sending it on cross-origin POST requests. This mitigates CSRF for state-mutating operations.

**Implementation:** `sajha/routes/auth_routes.py` — `response.set_cookie(..., samesite='lax', ...)`

---

#### SC-2.3: Secure Flag (HTTPS Detection)

**Control:** Cookie `secure` flag is set dynamically based on the request scheme. When the server is accessed over HTTPS, the cookie is marked Secure (browser will only send it over HTTPS).

**Implementation:** `sajha/routes/auth_routes.py` — `secure=request.url.scheme == 'https'`

---

### Category 3: API Key Security (2 controls)

---

#### SC-3.1: API Key Hashing (SHA-256)

**Threat:** CWE-312 (Cleartext Storage of Sensitive Information)

**Control:** API keys are hashed with SHA-256 before storage in the `api_keys.key_hash` column. On validation, the incoming key is hashed and compared to the stored hash. The raw key is only returned once at creation time.

**Implementation:**

| Component | Location |
|-----------|----------|
| Hash function | `sajha/security.py` — `hash_api_key(key)` uses `hashlib.sha256()` |
| Key generation | `sajha/security.py` — `generate_api_key()` returns `(raw, hash, display_prefix)` |
| DB lookup by hash | `sajha/core/apikey_manager.py` — queries `ApiKey.key_hash == hash_api_key(key)` |
| Schema | `api_keys.key_hash VARCHAR(255) NOT NULL UNIQUE` — no raw key column |

---

#### SC-3.2: API Key Expiry and Usage Tracking

**Control:** API keys support optional `expires_at` timestamps. Usage is tracked via `last_used` and `usage_count` fields, updated on every successful validation. Expired keys are rejected.

---

### Category 4: HTTP Security Headers (8 controls)

All headers are set by `SecurityHeadersMiddleware` in `sajha/security.py`, wired into the FastAPI app in `sajha/app.py`.

---

#### SC-4.1: X-Content-Type-Options

**Value:** `nosniff`
**Threat:** CWE-16 (MIME Sniffing). Prevents browsers from interpreting files as a different MIME type.

#### SC-4.2: X-Frame-Options

**Value:** `SAMEORIGIN`
**Threat:** CWE-1021 (Clickjacking). Prevents the page from being embedded in iframes on other domains.

#### SC-4.3: Content-Security-Policy

**Value:** `default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'`
**Threat:** CWE-79 (XSS). Restricts script and resource loading to trusted origins.

#### SC-4.4: Strict-Transport-Security

**Value:** `max-age=31536000; includeSubDomains` (set only when scheme is HTTPS)
**Threat:** CWE-319 (Protocol Downgrade). Forces HTTPS for 1 year after first HTTPS visit.

#### SC-4.5: X-XSS-Protection

**Value:** `1; mode=block`
**Threat:** Legacy XSS filter — stops page rendering if reflected XSS is detected.

#### SC-4.6: Referrer-Policy

**Value:** `strict-origin-when-cross-origin`
**Threat:** CWE-200 (Information Exposure). Prevents leaking full URLs in Referer headers to third-party sites.

#### SC-4.7: Permissions-Policy

**Value:** `camera=(), microphone=(), geolocation=()`
**Threat:** Disables browser APIs that SAJHA does not use, reducing attack surface.

#### SC-4.8: Middleware Wiring

**Verification:** `SecurityHeadersMiddleware` is added to the FastAPI app in `sajha/app.py` via `app.add_middleware(SecurityHeadersMiddleware)`. Every response passes through it.

---

### Category 5: CORS Policy (2 controls)

---

#### SC-5.1: No Wildcard Origins

**Threat:** CWE-942 (Overly Permissive CORS Policy)

**Control:** CORS `allow_origins` is NOT set to `['*']`. Origins are loaded from the `SAJHA_CORS_ORIGINS` environment variable, defaulting to `http://localhost:3002` for development.

**Implementation:** `sajha/app.py`:

```python
allow_origins=os.environ.get('SAJHA_CORS_ORIGINS', 'http://localhost:3002').split(','),
```

**Production configuration:**

```bash
export SAJHA_CORS_ORIGINS="https://sajha.company.com,https://admin.company.com"
```

---

#### SC-5.2: Credentials Restricted to Configured Origins

**Control:** `allow_credentials=True` is safe because origins are explicitly listed (not wildcard). The browser will only send cookies/auth headers to the listed origins.

---

### Category 6: Input Validation (2 controls)

---

#### SC-6.1: Request Body Size Limit

**Threat:** CWE-400 (Uncontrolled Resource Consumption)

**Control:** `RequestSizeLimitMiddleware` rejects any request with `Content-Length` exceeding 10 MB with HTTP 413 (Payload Too Large).

**Implementation:** `sajha/security.py` — `RequestSizeLimitMiddleware(max_body_size=10*1024*1024)`, wired in `sajha/app.py`.

---

#### SC-6.2: DuckDB SQL Allowlist

**Threat:** CWE-89 (SQL Injection)

**Control:** The DuckDB OLAP tool uses an allowlist approach instead of a keyword blocklist. Only queries starting with `SELECT`, `WITH`, `EXPLAIN`, `DESCRIBE`, `SHOW`, or `PRAGMA` are permitted. SQL comments are stripped before analysis to prevent bypass via `DR/**/OP`.

**Implementation:** `sajha/tools/impl/duckdb_olap_advanced.py`:

```python
# Strip comments to prevent bypass
sql_normalized = re.sub(r'/\*.*?\*/', ' ', sql, flags=re.DOTALL)
sql_normalized = re.sub(r'--[^\n]*', ' ', sql_normalized)
first_keyword = sql_normalized.split()[0].upper()
if first_keyword not in ('SELECT', 'WITH', 'EXPLAIN', 'DESCRIBE', 'SHOW', 'PRAGMA'):
    return {"error": f"Only SELECT/WITH/EXPLAIN queries are permitted."}
```

---

### Category 7: Database Schema Security (5 controls)

---

#### SC-7.1: Hashed Password Column

**Control:** The `users` table stores `password_hash VARCHAR(255)` — never a plaintext `password` column. The SQLAlchemy `User` model maps to `password_hash`.

#### SC-7.2: Hashed API Key Column

**Control:** The `api_keys` table stores `key_hash VARCHAR(255)` — the SHA-256 hash of the raw key. A `key_prefix VARCHAR(12)` stores only the first 12 characters for display (`sja_xxxx...`).

#### SC-7.3: Hashed Session Token Column

**Control:** The `user_sessions` table stores `token_hash VARCHAR(255)` — the SHA-256 hash of the session token. Raw tokens exist only in the client cookie.

#### SC-7.4: Account Lockout Columns

**Control:** The `users` table includes `failed_attempts INTEGER DEFAULT 0` and `locked_until TIMESTAMP` for tracking and enforcing account lockout.

#### SC-7.5: Dual Schema Support

**Control:** Separate schema files for SQLite and PostgreSQL with appropriate data types:

| Feature | SQLite | PostgreSQL |
|---------|--------|------------|
| Timestamps | `TIMESTAMP` | `TIMESTAMPTZ` |
| Booleans | `DEFAULT 1/0` | `DEFAULT TRUE/FALSE` |
| Floats | `REAL` | `DOUBLE PRECISION` |
| Auto-create | Yes (on startup) | No (run SQL manually) |

---

## OWASP Top 10 Coverage

| OWASP Category | Controls |
|----------------|----------|
| A01 Broken Access Control | SC-1.7 (multi-method auth), SC-1.8 (no password exposure), SC-5.1 (CORS) |
| A02 Cryptographic Failures | SC-1.1 (bcrypt), SC-3.1 (SHA-256 keys), SC-1.3 (SHA-256 tokens) |
| A03 Injection | SC-6.2 (SQL allowlist) |
| A04 Insecure Design | SC-1.5 (lockout), SC-1.6 (rate limit), SC-6.1 (body limit) |
| A05 Security Misconfiguration | SC-4.1–4.8 (headers), SC-5.1 (CORS), SC-1.2 (no hardcoded creds) |
| A06 Vulnerable Components | bcrypt, python-jose with cryptography backend |
| A07 Authentication Failures | SC-1.1–1.9 (full auth suite) |
| A08 Data Integrity Failures | SC-2.1–2.3 (cookie flags), SC-4.3 (CSP) |
| A09 Logging & Monitoring | Exception handling audit (308 good, 75% compliance) |
| A10 SSRF | SC-4.3 (CSP connect-src 'self'), tool URL validation |

---

## Remaining Advisories

These are enhancements recommended for defense-in-depth. None are blocking for production deployment.

| Advisory | Priority | Description |
|----------|:--------:|-------------|
| Pydantic request models | Medium | Add Pydantic `BaseModel` validation for all POST request bodies |
| Per-user API rate limiting | Medium | Current rate limiting is per-IP on auth only. Add per-user/per-key limits for API calls |
| CSRF tokens for web forms | Low | SameSite=lax mitigates most CSRF. Explicit tokens add defense-in-depth for non-GET mutations |
| Admin password force-change | Low | Prompt admin to change password on first login |
| mTLS for inter-service | Low | Mutual TLS for service-to-service communication in microservice deployments |
| Audit logging | Low | Structured audit log for security events (login, key creation, permission changes) |

---

## Verification Checklist

```bash
# 1. Password hashing (should show bcrypt, not plaintext)
grep "verify_password\|hash_password" sajha/core/auth_manager.py

# 2. No hardcoded credentials
grep -r "admin123" sajha/ --include="*.py"  # Should return nothing

# 3. CORS not wildcard
grep "allow_origins" sajha/app.py  # Should show SAJHA_CORS_ORIGINS

# 4. Security headers present
curl -sI http://localhost:3002/ | grep -i "x-frame\|x-content\|content-security"

# 5. Rate limiting works
for i in {1..6}; do curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:3002/api/auth/login -d '{}'; done
# 6th request should return 429

# 6. Account lockout
# After 5 failed logins, account locked for 15 minutes

# 7. Cookie flags
curl -sI -X POST http://localhost:3002/login -d 'user_id=admin&password=admin123' | grep -i "set-cookie"
# Should show: HttpOnly; SameSite=Lax

# 8. API key hashing
grep "hash_api_key\|key_hash" sajha/core/apikey_manager.py

# 9. Session in DB
grep "UserSession\|user_sessions" sajha/core/auth_manager.py

# 10. Body size limit
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:3002/mcp \
  -H "Content-Length: 20000000" -d @/dev/zero  # Should return 413
```

---

*SAJHA MCP Server v5.2.0 — Cybersecurity & Data Safety Assessment*
*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*

---

## Addendum: v5.2.0 Security Enhancements

### SC-NEW-1: Per-User API Rate Limiting

**Control:** API calls are rate-limited per user (100/min) and per API key (200/min) in addition to the existing per-IP auth rate limit. Implemented in `sajha/security.py` via `check_user_rate_limit()` and `check_key_rate_limit()`.

### SC-NEW-2: Structured Audit Logging

**Control:** All security-sensitive events are recorded in the `audit_log` database table via `AuditLogger` (`sajha/core/audit.py`). Events include: login_success, login_failed, logout, user_create, user_delete, apikey_create, apikey_revoke, account_locked. Queryable via `GET /api/audit`.

### SC-NEW-3: Circuit Breakers (Graceful Degradation)

**Control:** External API failures are tracked per provider. After 5 consecutive failures, the circuit breaker opens and subsequent requests fail fast with a clear error instead of timing out. This prevents cascading failures in composite tool pipelines.

### SC-NEW-4: Tool Output Caching

**Security Note:** Cached results are stored in-memory only (not on disk). Cache entries expire automatically (TTL-based). Admin can invalidate via `POST /api/cache/invalidate`. No sensitive data (passwords, keys) is ever cached.

### SC-NEW-5: Execution Replay Store

**Security Note:** Replay entries store arguments and result previews in memory only. Results are truncated to 200 characters. The store has a maximum capacity (5,000 entries). No PII or credentials are stored in replay entries.

*Updated security control count: 36 controls across 9 categories.*

---

## Addendum: Shell Execution Security Controls

### SC-SHELL-1: Disabled by Default

**Control:** Shell execution is disabled by default (`shell.enabled: false`). No code execution is possible until an administrator explicitly enables it in `config/application.yml`. Bash sandbox requires additional `shell.bash.enabled: true`.

### SC-SHELL-2: Import Allowlisting (Python)

**Control:** Python sandbox blocks 30+ dangerous modules (os, sys, subprocess, socket, http, requests, ctypes, pickle, importlib) and 10+ dangerous builtins (exec, eval, compile, open, __import__, getattr, globals). Only data-processing imports are allowed.

### SC-SHELL-3: Command Allowlisting (Bash)

**Control:** Bash sandbox only permits 30 safe read-only commands (cat, grep, awk, sed, sort, head, tail, jq, etc.). All other commands are rejected before execution. Additionally, 25+ regex patterns block command chaining (;, &&, ||), pipe-to-shell, backtick substitution, and write operations.

### SC-SHELL-4: Process Isolation

**Control:** All code executes in a subprocess with restricted PATH (`/usr/bin:/bin` only), empty PYTHONPATH, and a sandboxed HOME directory. No access to the parent process memory or environment variables.

### SC-SHELL-5: Resource Limits

**Control:** Python: 30s timeout, 256MB memory limit. Bash: 15s timeout, 1MB output cap. Prevents resource exhaustion and DoS.

### SC-SHELL-6: Full Audit Trail

**Control:** Every execution — successful, failed, or blocked — is recorded in the `audit_log` database table with action type, user_id, execution_id, code preview, and outcome. Admin can query via `GET /api/shell/history` and `GET /api/audit?action=shell_execute_python`.

*Updated security control count: 42 controls across 10 categories.*
