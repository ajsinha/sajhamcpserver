-- ============================================================================
-- SAJHA MCP Server v3 — Schema Creation
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
--
-- This is the single source of truth for database schema.
-- Runs automatically on startup (idempotent via IF NOT EXISTS).
-- Portable: works on both SQLite and PostgreSQL.
-- ============================================================================

-- ── Users ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS users (
    id              VARCHAR(36)  PRIMARY KEY,
    user_id         VARCHAR(100) NOT NULL UNIQUE,
    user_name       VARCHAR(255) NOT NULL,
    email           VARCHAR(255),
    password_hash   VARCHAR(255) NOT NULL,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    last_login      TIMESTAMP,
    oauth_provider  VARCHAR(50),
    oauth_subject   VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS ix_users_user_id ON users(user_id);


-- ── Roles ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS roles (
    id              VARCHAR(36)  PRIMARY KEY,
    name            VARCHAR(100) NOT NULL UNIQUE,
    description     VARCHAR(500),
    is_system       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_roles_name ON roles(name);


-- ── User ↔ Role (many-to-many) ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_roles (
    user_id         VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         VARCHAR(36)  NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);


-- ── Permissions ─────────────────────────────────────────────────────────────
--
-- Fine-grained access control per role.
-- resource_type:  '*', 'tool', 'prompt', 'studio', 'report', 'admin'
-- resource_name:  '*', 'duckdb_*', 'wikipedia_search', etc. (fnmatch patterns)
-- actions:        '*', 'execute', 'read', 'write', 'delete' (comma-separated)

CREATE TABLE IF NOT EXISTS permissions (
    id              VARCHAR(36)  PRIMARY KEY,
    role_id         VARCHAR(36)  NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    resource_type   VARCHAR(50)  NOT NULL,
    resource_name   VARCHAR(255) NOT NULL DEFAULT '*',
    actions         VARCHAR(255) NOT NULL DEFAULT '*'
);

CREATE INDEX IF NOT EXISTS ix_perm_role_resource ON permissions(role_id, resource_type, resource_name);


-- ── API Keys ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS api_keys (
    id              VARCHAR(36)  PRIMARY KEY,
    key_hash        VARCHAR(255) NOT NULL UNIQUE,
    key_prefix      VARCHAR(12)  NOT NULL,
    name            VARCHAR(255) NOT NULL,
    description     VARCHAR(500),
    owner_id        VARCHAR(36)  REFERENCES users(id) ON DELETE SET NULL,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP,
    last_used       TIMESTAMP,
    usage_count     INTEGER      NOT NULL DEFAULT 0,
    tool_access_mode VARCHAR(20) NOT NULL DEFAULT 'all',
    tool_access_list TEXT
);

CREATE INDEX IF NOT EXISTS ix_api_keys_hash ON api_keys(key_hash);


-- ── User Sessions ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_sessions (
    id              VARCHAR(36)  PRIMARY KEY,
    token_hash      VARCHAR(255) NOT NULL UNIQUE,
    user_id         VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_activity   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP    NOT NULL,
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS ix_session_token ON user_sessions(token_hash);
CREATE INDEX IF NOT EXISTS ix_session_expires ON user_sessions(expires_at);


-- ── Tool Usage Events ───────────────────────────────────────────────────────
--
-- Every tool execution is logged here. Foundation for all reporting.

CREATE TABLE IF NOT EXISTS tool_usage_events (
    id                VARCHAR(36)  PRIMARY KEY,
    tool_name         VARCHAR(255) NOT NULL,
    user_id           VARCHAR(100),
    auth_type         VARCHAR(20),
    timestamp         TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms       INTEGER,
    success           BOOLEAN      NOT NULL DEFAULT TRUE,
    error_message     TEXT,
    arguments_hash    VARCHAR(64),
    result_size_bytes INTEGER,
    client_ip         VARCHAR(45),
    user_agent        VARCHAR(500)
);

CREATE INDEX IF NOT EXISTS ix_tool_usage_tool      ON tool_usage_events(tool_name);
CREATE INDEX IF NOT EXISTS ix_tool_usage_user      ON tool_usage_events(user_id);
CREATE INDEX IF NOT EXISTS ix_tool_usage_timestamp ON tool_usage_events(timestamp);
CREATE INDEX IF NOT EXISTS ix_tool_usage_tool_time ON tool_usage_events(tool_name, timestamp);
CREATE INDEX IF NOT EXISTS ix_tool_usage_user_time ON tool_usage_events(user_id, timestamp);


-- ── Audit Log ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id              VARCHAR(36)  PRIMARY KEY,
    timestamp       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id        VARCHAR(100),
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(255),
    details         TEXT,
    ip_address      VARCHAR(45)
);

CREATE INDEX IF NOT EXISTS ix_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS ix_audit_action    ON audit_log(action);


-- ── A2A Tasks ───────────────────────────────────────────────────────────────
--
-- Agent-to-Agent protocol task lifecycle.
-- Valid states: submitted, working, input-required, completed, failed, cancelled

CREATE TABLE IF NOT EXISTS a2a_tasks (
    id              VARCHAR(36)  PRIMARY KEY,
    session_id      VARCHAR(100),
    state           VARCHAR(20)  NOT NULL DEFAULT 'submitted',
    input_message   TEXT,
    output_artifacts TEXT,
    error_message   TEXT,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    caller_agent    VARCHAR(255),
    metadata_json   TEXT
);

CREATE INDEX IF NOT EXISTS ix_a2a_session ON a2a_tasks(session_id);
