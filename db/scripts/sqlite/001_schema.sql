-- ============================================================================
-- SAJHA MCP Server v5.1.0 — SQLite Schema
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
-- Generated from SQLAlchemy models (single source of truth).
-- Auto-created on startup. Idempotent (IF NOT EXISTS).
-- ============================================================================

-- ── A2ATask ──
CREATE TABLE IF NOT EXISTS a2a_tasks (
    id                   VARCHAR(36)    PRIMARY KEY,
    session_id           VARCHAR(100)   ,
    state                VARCHAR(20)    NOT NULL DEFAULT 'submitted',
    input_message        TEXT           ,
    output_artifacts     TEXT           ,
    error_message        TEXT           ,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    caller_agent         VARCHAR(255)   ,
    metadata_json        TEXT           
);

-- ── ApiKey ──
CREATE TABLE IF NOT EXISTS api_keys (
    id                   VARCHAR(36)    PRIMARY KEY,
    key_hash             VARCHAR(255)   NOT NULL UNIQUE,
    key_prefix           VARCHAR(12)    NOT NULL,
    name                 VARCHAR(255)   NOT NULL,
    description          VARCHAR(500)   ,
    owner_id             VARCHAR(36)    ,
    enabled              BOOLEAN        NOT NULL DEFAULT 1,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at           TIMESTAMP      ,
    last_used            TIMESTAMP      ,
    usage_count          INTEGER        NOT NULL DEFAULT 0,
    tool_access_mode     VARCHAR(20)    NOT NULL DEFAULT 'all',
    tool_access_list     TEXT           
);

-- ── AuditLog ──
CREATE TABLE IF NOT EXISTS audit_log (
    id                   VARCHAR(36)    PRIMARY KEY,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id              VARCHAR(100)   ,
    action               VARCHAR(100)   NOT NULL,
    resource_type        VARCHAR(50)    ,
    resource_id          VARCHAR(255)   ,
    details              TEXT           ,
    ip_address           VARCHAR(45)    
);

-- ── CompositeToolStepRecord ──
CREATE TABLE IF NOT EXISTS composite_tool_steps (
    id                   VARCHAR(36)    PRIMARY KEY,
    composite_tool_id    VARCHAR(36)    NOT NULL,
    step_order           INTEGER        DEFAULT 0,
    tool_name            VARCHAR(255)   NOT NULL,
    output_key           VARCHAR(100)   NOT NULL,
    execution_mode       VARCHAR(20)    DEFAULT 'parallel',
    param_mapping        TEXT           ,
    static_params        TEXT           ,
    condition            TEXT           
);

-- ── CompositeToolRecord ──
CREATE TABLE IF NOT EXISTS composite_tools (
    id                   VARCHAR(36)    PRIMARY KEY,
    name                 VARCHAR(255)   NOT NULL UNIQUE,
    description          TEXT           ,
    arrangement          VARCHAR(20)    NOT NULL DEFAULT 'sibling',
    master_tool          VARCHAR(255)   NOT NULL,
    master_output_key    VARCHAR(100)   DEFAULT 'master',
    record_path          VARCHAR(255)   ,
    enabled              BOOLEAN        NOT NULL DEFAULT 1,
    created_by           VARCHAR(100)   ,
    created_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ── LLMModelRecord ──
CREATE TABLE IF NOT EXISTS llm_models (
    id                   VARCHAR(36)    PRIMARY KEY,
    provider_type        VARCHAR(50)    NOT NULL,
    model_id             VARCHAR(255)   NOT NULL,
    display_name         VARCHAR(255)   NOT NULL,
    context_window       INTEGER        DEFAULT 0,
    max_output_tokens    INTEGER        ,
    input_cost_per_1k    REAL           DEFAULT 0,
    output_cost_per_1k   REAL           DEFAULT 0,
    supports_tools       BOOLEAN        DEFAULT 1,
    supports_vision      BOOLEAN        DEFAULT 0,
    supports_streaming   BOOLEAN        DEFAULT 1,
    supports_embeddings  BOOLEAN        DEFAULT 0,
    tags                 TEXT           ,
    is_default           BOOLEAN        DEFAULT 0,
    enabled              BOOLEAN        DEFAULT 1,
    created_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ── LLMProviderRecord ──
CREATE TABLE IF NOT EXISTS llm_providers (
    id                   VARCHAR(36)    PRIMARY KEY,
    provider_type        VARCHAR(50)    NOT NULL UNIQUE,
    display_name         VARCHAR(255)   NOT NULL,
    enabled              BOOLEAN        NOT NULL DEFAULT 1,
    api_key              VARCHAR(500)   ,
    base_url             VARCHAR(500)   ,
    region               VARCHAR(50)    ,
    extra_config         TEXT           ,
    is_default           BOOLEAN        NOT NULL DEFAULT 0,
    created_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ── Permission ──
CREATE TABLE IF NOT EXISTS permissions (
    id                   VARCHAR(36)    PRIMARY KEY,
    role_id              VARCHAR(36)    NOT NULL,
    resource_type        VARCHAR(50)    NOT NULL,
    resource_name        VARCHAR(255)   NOT NULL DEFAULT '*',
    actions              VARCHAR(255)   NOT NULL DEFAULT '*'
);

-- ── PromptTag ──
CREATE TABLE IF NOT EXISTS prompt_tags (
    prompt_id            VARCHAR(36)    PRIMARY KEY,
    tag                  VARCHAR(100)   PRIMARY KEY
);

-- ── Prompt ──
CREATE TABLE IF NOT EXISTS prompts (
    id                   VARCHAR(36)    PRIMARY KEY,
    name                 VARCHAR(255)   NOT NULL UNIQUE,
    description          TEXT           ,
    category             VARCHAR(100)   ,
    template             TEXT           NOT NULL,
    arguments_json       TEXT           ,
    created_by           VARCHAR(100)   ,
    enabled              BOOLEAN        NOT NULL DEFAULT 1,
    created_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ── Role ──
CREATE TABLE IF NOT EXISTS roles (
    id                   VARCHAR(36)    PRIMARY KEY,
    name                 VARCHAR(100)   NOT NULL UNIQUE,
    description          VARCHAR(500)   ,
    is_system            BOOLEAN        NOT NULL DEFAULT 0,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── TenantRecord ──
CREATE TABLE IF NOT EXISTS tenants (
    id                   VARCHAR(36)    PRIMARY KEY,
    name                 VARCHAR(255)   NOT NULL UNIQUE,
    enabled              BOOLEAN        NOT NULL DEFAULT 1,
    tool_patterns        TEXT           ,
    blocked_tools        TEXT           ,
    quota_json           TEXT           ,
    data_prefix          VARCHAR(255)   ,
    created_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ── ToolUsageEvent ──
CREATE TABLE IF NOT EXISTS tool_usage_events (
    id                   VARCHAR(36)    PRIMARY KEY,
    tool_name            VARCHAR(255)   NOT NULL,
    user_id              VARCHAR(100)   ,
    auth_type            VARCHAR(20)    ,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms          INTEGER        ,
    success              BOOLEAN        NOT NULL DEFAULT 1,
    error_message        TEXT           ,
    arguments_hash       VARCHAR(64)    ,
    result_size_bytes    INTEGER        ,
    client_ip            VARCHAR(45)    ,
    user_agent           VARCHAR(500)   
);

-- ── ToolVersionRecord ──
CREATE TABLE IF NOT EXISTS tool_versions (
    id                   VARCHAR(36)    PRIMARY KEY,
    tool_name            VARCHAR(255)   NOT NULL,
    version              VARCHAR(50)    NOT NULL,
    lifecycle            VARCHAR(20)    DEFAULT 'active',
    deprecated_at        TIMESTAMP      ,
    sunset_date          VARCHAR(20)    ,
    successor            VARCHAR(255)   ,
    changelog            TEXT           ,
    created_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
);

-- ── UserSession ──
CREATE TABLE IF NOT EXISTS user_sessions (
    id                   VARCHAR(36)    PRIMARY KEY,
    token_hash           VARCHAR(255)   NOT NULL UNIQUE,
    user_id              VARCHAR(36)    NOT NULL,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_activity        TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at           TIMESTAMP      NOT NULL,
    ip_address           VARCHAR(45)    ,
    user_agent           VARCHAR(500)   
);

-- ── User ──
CREATE TABLE IF NOT EXISTS users (
    id                   VARCHAR(36)    PRIMARY KEY,
    user_id              VARCHAR(100)   NOT NULL UNIQUE,
    user_name            VARCHAR(255)   NOT NULL,
    email                VARCHAR(255)   ,
    password_hash        VARCHAR(255)   NOT NULL,
    enabled              BOOLEAN        NOT NULL DEFAULT 1,
    created_at           TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP      DEFAULT CURRENT_TIMESTAMP,
    last_login           TIMESTAMP      ,
    oauth_provider       VARCHAR(50)    ,
    oauth_subject        VARCHAR(255)   ,
    failed_attempts      INTEGER        NOT NULL DEFAULT 0,
    locked_until         TIMESTAMP      
);

-- ── Junction: User-Role ──
CREATE TABLE IF NOT EXISTS user_roles (
    user_id              VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id              VARCHAR(36)  NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

-- ── Junction: Tenant-User ──
CREATE TABLE IF NOT EXISTS tenant_users (
    tenant_id            VARCHAR(36)  NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id              VARCHAR(36)  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY (tenant_id, user_id)
);

-- ── Rate Limit Log ──
CREATE TABLE IF NOT EXISTS rate_limit_log (
    id                   VARCHAR(36)  PRIMARY KEY,
    rate_key             VARCHAR(255) NOT NULL,
    endpoint             VARCHAR(255) NOT NULL,
    created_at           TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_ratelimit ON rate_limit_log(rate_key, endpoint, created_at);

-- ── Indexes ──
CREATE INDEX IF NOT EXISTS ix_users_user_id ON users(user_id);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE INDEX IF NOT EXISTS ix_apikeys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS ix_session_token ON user_sessions(token_hash);
CREATE INDEX IF NOT EXISTS ix_usage_tool ON tool_usage_events(tool_name);
CREATE INDEX IF NOT EXISTS ix_usage_time ON tool_usage_events(created_at);
CREATE INDEX IF NOT EXISTS ix_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(created_at);
