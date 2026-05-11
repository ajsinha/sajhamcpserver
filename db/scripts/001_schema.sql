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


-- ── Prompts (moved from JSON files to database in v3.1.0) ───────────────────
--
-- Stores all prompt templates. Replaces config/prompts/*.json.
-- PromptsRegistry reads from this table instead of filesystem.

CREATE TABLE IF NOT EXISTS prompts (
    id              VARCHAR(36)  PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    description     TEXT,
    category        VARCHAR(100),
    template        TEXT         NOT NULL,
    arguments_json  TEXT,
    created_by      VARCHAR(100),
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_prompts_name     ON prompts(name);
CREATE INDEX IF NOT EXISTS ix_prompts_category ON prompts(category);


-- ── Prompt Tags (many-to-many) ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS prompt_tags (
    prompt_id       VARCHAR(36)  NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    tag             VARCHAR(100) NOT NULL,
    PRIMARY KEY (prompt_id, tag)
);

CREATE INDEX IF NOT EXISTS ix_prompt_tags_tag ON prompt_tags(tag);


-- ── LLM Providers (registered AI providers — managed via Admin UI) ───────────

CREATE TABLE IF NOT EXISTS llm_providers (
    id              VARCHAR(36)  PRIMARY KEY,
    provider_type   VARCHAR(50)  NOT NULL UNIQUE,
    display_name    VARCHAR(255) NOT NULL,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    api_key         VARCHAR(500),
    base_url        VARCHAR(500),
    region          VARCHAR(50),
    extra_config    TEXT,
    is_default      BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ── LLM Models (available models per provider — managed via Admin UI) ────────

CREATE TABLE IF NOT EXISTS llm_models (
    id                  VARCHAR(36)   PRIMARY KEY,
    provider_type       VARCHAR(50)   NOT NULL,
    model_id            VARCHAR(255)  NOT NULL,
    display_name        VARCHAR(255)  NOT NULL,
    context_window      INTEGER       NOT NULL DEFAULT 0,
    max_output_tokens   INTEGER       NOT NULL DEFAULT 4096,
    input_cost_per_1k   REAL          NOT NULL DEFAULT 0.0,
    output_cost_per_1k  REAL          NOT NULL DEFAULT 0.0,
    supports_tools      BOOLEAN       NOT NULL DEFAULT TRUE,
    supports_vision     BOOLEAN       NOT NULL DEFAULT FALSE,
    supports_streaming  BOOLEAN       NOT NULL DEFAULT TRUE,
    supports_embeddings BOOLEAN       NOT NULL DEFAULT FALSE,
    tags                TEXT,
    is_default          BOOLEAN       NOT NULL DEFAULT FALSE,
    enabled             BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(provider_type, model_id)
);

CREATE INDEX IF NOT EXISTS ix_llm_models_provider ON llm_models(provider_type);

-- ── LLM Usage Tracking (token budget per user/model) ────────────────────────

CREATE TABLE IF NOT EXISTS llm_usage (
    id              VARCHAR(36)  PRIMARY KEY,
    user_id         VARCHAR(100) NOT NULL,
    provider        VARCHAR(50)  NOT NULL,
    model           VARCHAR(255) NOT NULL,
    input_tokens    INTEGER      NOT NULL DEFAULT 0,
    output_tokens   INTEGER      NOT NULL DEFAULT 0,
    cost_usd        REAL         NOT NULL DEFAULT 0.0,
    latency_ms      INTEGER      NOT NULL DEFAULT 0,
    timestamp       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_llm_usage_user ON llm_usage(user_id);
CREATE INDEX IF NOT EXISTS ix_llm_usage_ts   ON llm_usage(timestamp);

-- ── User AI Preferences (user-level model overrides) ────────────────────────

CREATE TABLE IF NOT EXISTS user_ai_preferences (
    user_id         VARCHAR(100) PRIMARY KEY,
    provider        VARCHAR(50),
    model           VARCHAR(255),
    temperature     REAL,
    max_tokens      INTEGER,
    updated_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- ── Composite Tools (declarative multi-tool orchestration) ──────────────────

CREATE TABLE IF NOT EXISTS composite_tools (
    id              VARCHAR(36)  PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    description     TEXT,
    arrangement     VARCHAR(20)  NOT NULL DEFAULT 'sibling',
    master_tool     VARCHAR(255) NOT NULL,
    master_output_key VARCHAR(100) NOT NULL DEFAULT 'master',
    record_path     VARCHAR(255),
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by      VARCHAR(100),
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS composite_tool_steps (
    id                VARCHAR(36)  PRIMARY KEY,
    composite_tool_id VARCHAR(36)  NOT NULL REFERENCES composite_tools(id) ON DELETE CASCADE,
    step_order        INTEGER      NOT NULL DEFAULT 0,
    tool_name         VARCHAR(255) NOT NULL,
    output_key        VARCHAR(100) NOT NULL,
    execution_mode    VARCHAR(20)  NOT NULL DEFAULT 'parallel',
    param_mapping     TEXT,
    static_params     TEXT,
    condition         TEXT
);

CREATE INDEX IF NOT EXISTS ix_comp_steps_tool ON composite_tool_steps(composite_tool_id);


-- ── Tenants (v4.0.0 — multi-tenancy) ───────────────────────────────────────

CREATE TABLE IF NOT EXISTS tenants (
    id              VARCHAR(36)  PRIMARY KEY,
    name            VARCHAR(255) NOT NULL UNIQUE,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    tool_patterns   TEXT,
    blocked_tools   TEXT,
    quota_json      TEXT,
    data_prefix     VARCHAR(255),
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── Tool Versions (v4.0.0 — versioning & deprecation) ──────────────────────

CREATE TABLE IF NOT EXISTS tool_versions (
    id              VARCHAR(36)  PRIMARY KEY,
    tool_name       VARCHAR(255) NOT NULL,
    version         VARCHAR(50)  NOT NULL,
    lifecycle       VARCHAR(20)  NOT NULL DEFAULT 'active',
    deprecated_at   TIMESTAMP,
    sunset_date     VARCHAR(20),
    successor       VARCHAR(255),
    changelog       TEXT,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tool_name, version)
);
