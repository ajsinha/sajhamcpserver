-- ============================================================================
-- SAJHA MCP Server: the database schema (PostgreSQL)
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
--
-- Every table, column, key and index SAJHA uses. There are no migrations: an
-- operator runs this one file, once, before SAJHA's first start. SAJHA never runs
-- DDL on PostgreSQL; at start-up it checks that these tables and columns exist and
-- refuses to start, naming what is missing, when they do not (db.schema_check).
--
--   psql -v ON_ERROR_STOP=1 -h HOST -U USER -d DBNAME -f db/scripts/postgresql/schema.sql
--   psql -v ON_ERROR_STOP=1 -h HOST -U USER -d DBNAME -f db/scripts/postgresql/seed.sql   # new database only
--
-- Idempotent (IF NOT EXISTS) and atomic (one transaction). It never alters an
-- existing table: when a release changes the schema, its CHANGELOG entry lists the
-- SQL to run. Kept in step with db/scripts/sqlite/schema.sql and with the code by
-- tests/test_db_schema.py. Guide: docs/getting-started/Database Setup.md
--
-- Timestamps are TIMESTAMPTZ (SAJHA's sessions run in UTC), except connected_accounts,
-- whose code works in naive UTC and so uses TIMESTAMP.
-- ============================================================================

BEGIN;

-- ── Users, roles, permissions (sajha/db/models) ──
CREATE TABLE IF NOT EXISTS users (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    user_id              VARCHAR(100)     NOT NULL,
    user_name            VARCHAR(255)     NOT NULL,
    email                VARCHAR(255),
    password_hash        VARCHAR(255)     NOT NULL,
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP,
    last_login           TIMESTAMPTZ,
    oauth_provider       VARCHAR(50),
    oauth_subject        VARCHAR(255),
    failed_attempts      INTEGER          NOT NULL DEFAULT 0,
    locked_until         TIMESTAMPTZ,
    must_change_password BOOLEAN          NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_user_id ON users (user_id);

CREATE TABLE IF NOT EXISTS roles (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    name                 VARCHAR(100)     NOT NULL,
    description          VARCHAR(500),
    is_system            BOOLEAN          NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_roles_name ON roles (name);

CREATE TABLE IF NOT EXISTS user_roles (
    user_id              VARCHAR(36)      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role_id              VARCHAR(36)      NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS permissions (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    role_id              VARCHAR(36)      NOT NULL REFERENCES roles (id) ON DELETE CASCADE,
    resource_type        VARCHAR(50)      NOT NULL,
    resource_name        VARCHAR(255)     NOT NULL DEFAULT '*',
    actions              VARCHAR(255)     NOT NULL DEFAULT '*'
);
CREATE INDEX IF NOT EXISTS ix_perm_role_resource ON permissions (role_id, resource_type, resource_name);

-- ── API keys and sign-in sessions ──
CREATE TABLE IF NOT EXISTS api_keys (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    key_hash             VARCHAR(255)     NOT NULL,
    key_prefix           VARCHAR(12)      NOT NULL,
    name                 VARCHAR(255)     NOT NULL,
    description          VARCHAR(500),
    owner_id             VARCHAR(36)      REFERENCES users (id) ON DELETE SET NULL,
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at           TIMESTAMPTZ,
    last_used            TIMESTAMPTZ,
    usage_count          INTEGER          NOT NULL DEFAULT 0,
    tool_access_mode     VARCHAR(20)      NOT NULL DEFAULT 'all',
    tool_access_list     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash);

CREATE TABLE IF NOT EXISTS user_sessions (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    token_hash           VARCHAR(255)     NOT NULL,
    user_id              VARCHAR(36)      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_activity        TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at           TIMESTAMPTZ      NOT NULL,
    ip_address           VARCHAR(45),
    user_agent           VARCHAR(500)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_user_sessions_token_hash ON user_sessions (token_hash);
CREATE INDEX IF NOT EXISTS ix_session_expires ON user_sessions (expires_at);
CREATE INDEX IF NOT EXISTS ix_session_user ON user_sessions (user_id);

-- ── Tool usage and audit ──
CREATE TABLE IF NOT EXISTS tool_usage_events (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    tool_name            VARCHAR(255)     NOT NULL,
    user_id              VARCHAR(100),
    auth_type            VARCHAR(20),
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration_ms          INTEGER,
    success              BOOLEAN          NOT NULL DEFAULT TRUE,
    error_message        TEXT,
    arguments_hash       VARCHAR(64),
    result_size_bytes    INTEGER,
    client_ip            VARCHAR(45),
    user_agent           VARCHAR(500)
);
CREATE INDEX IF NOT EXISTS ix_tool_usage_events_tool_name ON tool_usage_events (tool_name);
CREATE INDEX IF NOT EXISTS ix_tool_usage_events_user_id ON tool_usage_events (user_id);
CREATE INDEX IF NOT EXISTS ix_tool_usage_events_created_at ON tool_usage_events (created_at);
CREATE INDEX IF NOT EXISTS ix_tool_usage_tool_time ON tool_usage_events (tool_name, created_at);
CREATE INDEX IF NOT EXISTS ix_tool_usage_user_time ON tool_usage_events (user_id, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id              VARCHAR(100),
    action               VARCHAR(100)     NOT NULL,
    resource_type        VARCHAR(50),
    resource_id          VARCHAR(255),
    details              TEXT,
    ip_address           VARCHAR(45)
);
CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at);
CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action);

-- ── A2A tasks ──
CREATE TABLE IF NOT EXISTS a2a_tasks (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    session_id           VARCHAR(100),
    state                VARCHAR(20)      NOT NULL DEFAULT 'submitted',
    input_message        TEXT,
    output_artifacts     TEXT,
    error_message        TEXT,
    created_at           TIMESTAMPTZ      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP,
    caller_agent         VARCHAR(255),
    metadata_json        TEXT
);
CREATE INDEX IF NOT EXISTS ix_a2a_tasks_session_id ON a2a_tasks (session_id);

-- ── Prompts ──
CREATE TABLE IF NOT EXISTS prompts (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    name                 VARCHAR(255)     NOT NULL UNIQUE,
    description          TEXT,
    category             VARCHAR(100),
    template             TEXT             NOT NULL,
    arguments_json       TEXT,
    created_by           VARCHAR(100),
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    created_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prompt_tags (
    prompt_id            VARCHAR(36)      NOT NULL REFERENCES prompts (id) ON DELETE CASCADE,
    tag                  VARCHAR(100)     NOT NULL,
    PRIMARY KEY (prompt_id, tag)
);

-- ── LLM providers and models ──
CREATE TABLE IF NOT EXISTS llm_providers (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    provider_type        VARCHAR(50)      NOT NULL UNIQUE,
    display_name         VARCHAR(255)     NOT NULL,
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    api_key              VARCHAR(500),
    base_url             VARCHAR(500),
    region               VARCHAR(50),
    extra_config         TEXT,
    is_default           BOOLEAN          NOT NULL DEFAULT FALSE,
    created_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_models (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    provider_type        VARCHAR(50)      NOT NULL,
    model_id             VARCHAR(255)     NOT NULL,
    display_name         VARCHAR(255)     NOT NULL,
    context_window       INTEGER          DEFAULT 0,
    max_output_tokens    INTEGER          DEFAULT 4096,
    input_cost_per_1k    DOUBLE PRECISION DEFAULT 0,
    output_cost_per_1k   DOUBLE PRECISION DEFAULT 0,
    supports_tools       BOOLEAN          DEFAULT TRUE,
    supports_vision      BOOLEAN          DEFAULT FALSE,
    supports_streaming   BOOLEAN          DEFAULT TRUE,
    supports_embeddings  BOOLEAN          DEFAULT FALSE,
    tags                 TEXT,
    is_default           BOOLEAN          DEFAULT FALSE,
    enabled              BOOLEAN          DEFAULT TRUE,
    created_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP
);

-- ── Composite tools ──
CREATE TABLE IF NOT EXISTS composite_tools (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    name                 VARCHAR(255)     NOT NULL UNIQUE,
    description          TEXT,
    arrangement          VARCHAR(20)      NOT NULL DEFAULT 'sibling',
    master_tool          VARCHAR(255)     NOT NULL,
    master_output_key    VARCHAR(100)     DEFAULT 'master',
    record_path          VARCHAR(255),
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    created_by           VARCHAR(100),
    created_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS composite_tool_steps (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    composite_tool_id    VARCHAR(36)      NOT NULL REFERENCES composite_tools (id) ON DELETE CASCADE,
    step_order           INTEGER          DEFAULT 0,
    tool_name            VARCHAR(255)     NOT NULL,
    output_key           VARCHAR(100)     NOT NULL,
    execution_mode       VARCHAR(20)      DEFAULT 'parallel',
    param_mapping        TEXT,
    static_params        TEXT,
    condition            TEXT
);
CREATE INDEX IF NOT EXISTS ix_composite_steps_tool ON composite_tool_steps (composite_tool_id);

-- ── Tenants and tool versions ──
CREATE TABLE IF NOT EXISTS tenants (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    name                 VARCHAR(255)     NOT NULL UNIQUE,
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    tool_patterns        TEXT,
    blocked_tools        TEXT,
    quota_json           TEXT,
    data_prefix          VARCHAR(255),
    created_at           TIMESTAMPTZ      DEFAULT CURRENT_TIMESTAMP
);

-- ── State store: state.backend database, and the durable task store
--    (sajha/core/state/database.py). If state.database.url names another database,
--    run this file there too.
CREATE TABLE IF NOT EXISTS sajha_state (
    k                    VARCHAR(512)     NOT NULL PRIMARY KEY,
    v                    TEXT             NOT NULL,
    ver                  INTEGER          NOT NULL DEFAULT 0,
    expires_at           DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_sajha_state_expires_at ON sajha_state (expires_at);

CREATE TABLE IF NOT EXISTS sajha_state_events (
    id                   BIGINT           GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    channel              VARCHAR(200)     NOT NULL,
    payload              TEXT             NOT NULL,
    created_at           DOUBLE PRECISION NOT NULL
);

-- ── Usage ledger behind the Usage & cost dashboard (sajha/observability/usage.py) ──
CREATE TABLE IF NOT EXISTS obs_usage_events (
    id                   BIGINT           GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    ts                   TIMESTAMPTZ      NOT NULL,
    day                  VARCHAR(10)      NOT NULL,
    kind                 VARCHAR(8)       NOT NULL,
    user_id              VARCHAR(200),
    api_key              VARCHAR(200),
    roles                VARCHAR(500),
    auth_type            VARCHAR(20),
    tool                 VARCHAR(255),
    tool_group           VARCHAR(100),
    provider             VARCHAR(100),
    model                VARCHAR(200),
    outcome              VARCHAR(40),
    latency_ms           DOUBLE PRECISION,
    input_tokens         INTEGER,
    output_tokens        INTEGER,
    cost_usd             DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_obs_usage_day_kind ON obs_usage_events (day, kind);
CREATE INDEX IF NOT EXISTS ix_obs_usage_user_day ON obs_usage_events (user_id, day);
CREATE INDEX IF NOT EXISTS ix_obs_usage_ts ON obs_usage_events (ts);

-- ── Connected accounts token vault (sajha/accounts/vault.py): one row per (SAJHA user,
--    provider). token_ciphertext is AES-256-GCM ciphertext, never a token in clear.
CREATE TABLE IF NOT EXISTS connected_accounts (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    user_id              VARCHAR(200)     NOT NULL,
    provider             VARCHAR(64)      NOT NULL,
    account_login        VARCHAR(255),
    account_id           VARCHAR(255),
    scopes               VARCHAR(4000),
    token_ciphertext     TEXT             NOT NULL,
    key_id               VARCHAR(64)      NOT NULL,
    has_refresh_token    BOOLEAN          NOT NULL DEFAULT FALSE,
    expires_at           TIMESTAMP,
    status               VARCHAR(20)      NOT NULL,
    last_error           VARCHAR(500),
    created_at           TIMESTAMP        NOT NULL,
    updated_at           TIMESTAMP        NOT NULL,
    last_used_at         TIMESTAMP,
    last_refreshed_at    TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_connected_accounts_user_provider ON connected_accounts (user_id, provider);
CREATE INDEX IF NOT EXISTS ix_connected_accounts_provider ON connected_accounts (provider);


-- ── Ask SAJHA conversation memory (sajha/ai/memory.py); *_ts are epoch seconds ──
CREATE TABLE IF NOT EXISTS ai_conversations (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    user_id              VARCHAR(200)     NOT NULL,
    title                VARCHAR(200),
    summary              TEXT,
    summarized_through   INTEGER          NOT NULL DEFAULT 0,
    turn_count           INTEGER          NOT NULL DEFAULT 0,
    created_ts           DOUBLE PRECISION NOT NULL,
    updated_ts           DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_updated ON ai_conversations (user_id, updated_ts);

CREATE TABLE IF NOT EXISTS ai_conversation_turns (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    conversation_id      VARCHAR(36)      NOT NULL REFERENCES ai_conversations (id) ON DELETE CASCADE,
    user_id              VARCHAR(200)     NOT NULL,
    seq                  INTEGER          NOT NULL,
    question             TEXT             NOT NULL,
    standalone           TEXT,
    answer               TEXT,
    tools                VARCHAR(2000),
    stopped_by           VARCHAR(40),
    confidence           DOUBLE PRECISION,
    created_ts           DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_conversation_turns_conv_seq ON ai_conversation_turns (conversation_id, seq);
CREATE INDEX IF NOT EXISTS ix_ai_conversation_turns_user ON ai_conversation_turns (user_id);

-- ── Tamper-evident audit chain and its signed anchors (sajha/audit/chain.py) ──
CREATE TABLE IF NOT EXISTS audit_chain (
    id                   BIGINT           GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    chain_id             VARCHAR(100)     NOT NULL,
    seq                  BIGINT           NOT NULL,
    ts                   TIMESTAMPTZ      NOT NULL,
    event                VARCHAR(100)     NOT NULL,
    actor                VARCHAR(200),
    resource             VARCHAR(300),
    outcome              VARCHAR(40),
    record_json          TEXT             NOT NULL,
    prev_hash            VARCHAR(64)      NOT NULL,
    hash                 VARCHAR(64)      NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_chain_chain_seq ON audit_chain (chain_id, seq);
CREATE INDEX IF NOT EXISTS ix_audit_chain_ts ON audit_chain (ts);
CREATE INDEX IF NOT EXISTS ix_audit_chain_event ON audit_chain (event);

CREATE TABLE IF NOT EXISTS audit_anchors (
    id                   BIGINT           GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    chain_id             VARCHAR(100)     NOT NULL,
    seq                  BIGINT           NOT NULL,
    hash                 VARCHAR(64)      NOT NULL,
    ts                   TIMESTAMPTZ      NOT NULL,
    kid                  VARCHAR(100),
    alg                  VARCHAR(20)      NOT NULL,
    payload_json         TEXT             NOT NULL,
    signature            TEXT             NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_anchors_chain_seq ON audit_anchors (chain_id, seq);

-- ── Workflows: definitions, durable runs and per-step records (sajha/workflows/store.py);
-- times are epoch seconds. Design: docs/architecture/Workflows.md ──
CREATE TABLE IF NOT EXISTS workflows (
    name                 VARCHAR(100)     NOT NULL PRIMARY KEY,
    description          TEXT,
    definition_json      TEXT             NOT NULL,
    owner                VARCHAR(200)     NOT NULL,
    enabled              BOOLEAN          NOT NULL DEFAULT TRUE,
    published            BOOLEAN          NOT NULL DEFAULT FALSE,
    version              INTEGER          NOT NULL DEFAULT 1,
    created_at           DOUBLE PRECISION NOT NULL,
    updated_at           DOUBLE PRECISION NOT NULL,
    updated_by           VARCHAR(200)
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    workflow             VARCHAR(100)     NOT NULL,
    version              INTEGER          NOT NULL,
    status               VARCHAR(20)      NOT NULL,
    trigger_type         VARCHAR(20)      NOT NULL,
    trigger_id           VARCHAR(100),
    trigger_detail       TEXT,
    run_as               VARCHAR(200)     NOT NULL,
    started_by           VARCHAR(200),
    input_json           TEXT,
    output_json          TEXT,
    error                TEXT,
    idempotency_key      VARCHAR(200),
    parent_run_id        VARCHAR(36),
    from_step            VARCHAR(100),
    worker_id            VARCHAR(200),
    cancel_requested     BOOLEAN          NOT NULL DEFAULT FALSE,
    delivery_status      VARCHAR(200),
    definition_json      TEXT             NOT NULL,
    created_at           DOUBLE PRECISION NOT NULL,
    started_at           DOUBLE PRECISION,
    finished_at          DOUBLE PRECISION,
    heartbeat_at         DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_workflow_created ON workflow_runs (workflow, created_at);
CREATE INDEX IF NOT EXISTS ix_workflow_runs_status ON workflow_runs (status);
CREATE UNIQUE INDEX IF NOT EXISTS ux_workflow_runs_idempotency ON workflow_runs (workflow, idempotency_key);

CREATE TABLE IF NOT EXISTS workflow_run_steps (
    id                   BIGINT           GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    run_id               VARCHAR(36)      NOT NULL REFERENCES workflow_runs (id) ON DELETE CASCADE,
    step_id              VARCHAR(100)     NOT NULL,
    kind                 VARCHAR(20)      NOT NULL,
    status               VARCHAR(20)      NOT NULL,
    attempts             INTEGER          NOT NULL DEFAULT 0,
    input_json           TEXT,
    output_json          TEXT,
    error                TEXT,
    idempotency_key      VARCHAR(64),
    detail_json          TEXT,
    started_at           DOUBLE PRECISION,
    finished_at          DOUBLE PRECISION,
    duration_ms          DOUBLE PRECISION
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_workflow_run_steps_run_step ON workflow_run_steps (run_id, step_id);

-- ── Tool quality: saved test-harness and eval runs (sajha/quality/store.py); times are
--    epoch seconds. Design: docs/architecture/Tool Quality.md ──
CREATE TABLE IF NOT EXISTS quality_runs (
    id                   VARCHAR(36)      NOT NULL PRIMARY KEY,
    kind                 VARCHAR(10)      NOT NULL,
    name                 VARCHAR(255)     NOT NULL,
    status               VARCHAR(16)      NOT NULL,
    started_at           DOUBLE PRECISION NOT NULL,
    finished_at          DOUBLE PRECISION,
    created_by           VARCHAR(200),
    summary_json         TEXT,
    detail_json          TEXT
);
CREATE INDEX IF NOT EXISTS ix_quality_runs_kind_started ON quality_runs (kind, started_at);

COMMIT;

-- ============================================================================
-- OPTIONAL: pgvector store for document search (sajha/ai/rag/stores.py)
-- ============================================================================
-- SAJHA's document index (sajha_search_docs, "Ask the docs") keeps its passages in
-- process by default. With ai.rag.store auto (the default) or pgvector, it uses this
-- table instead when the database has the pgvector extension and the table exists.
-- It is not part of the schema check: run it only if you want the index in PostgreSQL.
-- Needs the pgvector extension installed on the server (https://github.com/pgvector/pgvector).
-- Uncomment and run once, as a user allowed to create extensions:
--
-- CREATE EXTENSION IF NOT EXISTS vector;
-- CREATE TABLE IF NOT EXISTS rag_chunks (
--     id                   VARCHAR(64)      NOT NULL PRIMARY KEY,
--     source               VARCHAR(200)     NOT NULL,
--     document             VARCHAR(1000)    NOT NULL,
--     doc_hash             VARCHAR(64)      NOT NULL,
--     embedder             VARCHAR(200)     NOT NULL,
--     ordinal              INTEGER          NOT NULL,
--     title                VARCHAR(500),
--     heading              VARCHAR(1000),
--     anchor               VARCHAR(300),
--     url                  VARCHAR(1000),
--     text                 TEXT             NOT NULL,
--     embedding            vector           NOT NULL
-- );
-- CREATE INDEX IF NOT EXISTS ix_rag_chunks_source_document ON rag_chunks (source, document);
--
-- An approximate-nearest-neighbour index needs a fixed dimension: declare the column as
-- vector(<dims>) for your embedding model (mock-embed: 256) and add
-- CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding ON rag_chunks USING hnsw (embedding vector_cosine_ops);
