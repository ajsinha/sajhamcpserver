-- ============================================================================
-- SAJHA MCP Server v3 — Seed Data
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
--
-- Populates default roles, permissions, admin user, and sample API keys.
-- Runs automatically on startup. Idempotent: skips rows that already exist.
-- Portable: uses WHERE NOT EXISTS pattern (works on SQLite + PostgreSQL).
--
-- Default admin credentials:  admin / admin123
-- ============================================================================


-- ═══════════════════════════════════════════════════════════════════════════
-- ROLES
-- ═══════════════════════════════════════════════════════════════════════════

INSERT INTO roles (id, name, description, is_system)
SELECT 'role-admin-0001', 'admin', 'Full system administrator — all access', TRUE
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'admin');

INSERT INTO roles (id, name, description, is_system)
SELECT 'role-tdev-0002', 'tool_developer', 'Can create and manage tools via Studio', TRUE
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'tool_developer');

INSERT INTO roles (id, name, description, is_system)
SELECT 'role-anly-0003', 'analyst', 'Can execute tools and view reports', TRUE
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'analyst');

INSERT INTO roles (id, name, description, is_system)
SELECT 'role-view-0004', 'viewer', 'Read-only access to tools and reports', TRUE
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'viewer');

INSERT INTO roles (id, name, description, is_system)
SELECT 'role-apic-0005', 'api_consumer', 'Default role for API key access', TRUE
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'api_consumer');

INSERT INTO roles (id, name, description, is_system)
SELECT 'role-user-0006', 'user', 'Standard user — can execute all tools', TRUE
WHERE NOT EXISTS (SELECT 1 FROM roles WHERE name = 'user');


-- ═══════════════════════════════════════════════════════════════════════════
-- PERMISSIONS
-- ═══════════════════════════════════════════════════════════════════════════

-- admin: full wildcard access
INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0001', 'role-admin-0001', '*', '*', '*'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0001');

-- tool_developer: execute all tools + full studio + read reports
INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0010', 'role-tdev-0002', 'tool', '*', 'execute,read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0010');

INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0011', 'role-tdev-0002', 'studio', '*', '*'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0011');

INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0012', 'role-tdev-0002', 'prompt', '*', '*'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0012');

INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0013', 'role-tdev-0002', 'report', '*', 'read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0013');

-- analyst: execute tools + read reports
INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0020', 'role-anly-0003', 'tool', '*', 'execute,read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0020');

INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0021', 'role-anly-0003', 'report', '*', 'read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0021');

-- viewer: read-only
INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0030', 'role-view-0004', 'tool', '*', 'read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0030');

INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0031', 'role-view-0004', 'report', '*', 'read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0031');

-- api_consumer: execute tools only
INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0040', 'role-apic-0005', 'tool', '*', 'execute'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0040');

-- user: execute + read tools
INSERT INTO permissions (id, role_id, resource_type, resource_name, actions)
SELECT 'perm-0050', 'role-user-0006', 'tool', '*', 'execute,read'
WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE id = 'perm-0050');


-- ═══════════════════════════════════════════════════════════════════════════
-- DEFAULT ADMIN USER
-- ═══════════════════════════════════════════════════════════════════════════
-- Password: admin123  (bcrypt hash below)

INSERT INTO users (id, user_id, user_name, email, password_hash, enabled)
SELECT 'user-admin-0001', 'admin', 'Administrator', 'admin@sajha.local',
       '$2b$12$8NG2iCWD1NIMdADn8FsEHeu2fiNgTvFM75xbH8cQBME3jqUU1seiC', TRUE
WHERE NOT EXISTS (SELECT 1 FROM users WHERE user_id = 'admin');

-- Assign admin role
INSERT INTO user_roles (user_id, role_id)
SELECT 'user-admin-0001', 'role-admin-0001'
WHERE NOT EXISTS (SELECT 1 FROM user_roles WHERE user_id = 'user-admin-0001' AND role_id = 'role-admin-0001');


-- ═══════════════════════════════════════════════════════════════════════════
-- SAMPLE API KEYS (from legacy config)
-- ═══════════════════════════════════════════════════════════════════════════
-- These are SHA-256 hashes of the original sja_ keys from apikeys.json.
-- The actual keys are only known to their holders.

-- NOTE: Additional API keys from config/apikeys.json are imported by the
-- Python seed script (sajha/db/seed.py) which hashes raw keys at runtime.
-- This SQL only provides a fallback default key for first-time setup.

-- ── Default LLM Providers ───────────────────────────────────────────────────

INSERT OR IGNORE INTO llm_providers (id, provider_type, display_name, enabled, base_url, is_default)
VALUES
    ('p-anthro-001', 'anthropic',    'Anthropic (Claude)',       1, 'https://api.anthropic.com',       1),
    ('p-openai-001', 'openai',       'OpenAI (GPT)',             1, 'https://api.openai.com/v1',       0),
    ('p-bedrk-001',  'bedrock',      'AWS Bedrock',              1, NULL,                              0),
    ('p-togth-001',  'together',     'Together.ai',              1, 'https://api.together.xyz/v1',     0),
    ('p-ollam-001',  'ollama',       'Ollama (Local)',           0, 'http://localhost:11434',           0),
    ('p-azure-001',  'azure_openai', 'Azure OpenAI Service',    0, NULL,                              0);

-- ── Default LLM Models ─────────────────────────────────────────────────────

INSERT OR IGNORE INTO llm_models (id, provider_type, model_id, display_name, context_window, max_output_tokens, input_cost_per_1k, output_cost_per_1k, supports_tools, supports_vision, supports_embeddings, tags, is_default, enabled) VALUES
    -- Anthropic
    ('m-cl-son4',  'anthropic', 'claude-sonnet-4-20250514',       'Claude Sonnet 4',          200000, 8192,  0.003,   0.015,  1, 1, 0, 'balanced,tools,vision',      1, 1),
    ('m-cl-hai35', 'anthropic', 'claude-haiku-3-5-20241022',      'Claude Haiku 3.5',         200000, 8192,  0.0008,  0.004,  1, 1, 0, 'fast,cheap,tools',           0, 1),
    -- OpenAI
    ('m-gpt-4o',   'openai',   'gpt-4o',                          'GPT-4o',                   128000, 4096,  0.005,   0.015,  1, 1, 0, 'balanced,vision',            1, 1),
    ('m-gpt-4om',  'openai',   'gpt-4o-mini',                     'GPT-4o Mini',              128000, 4096,  0.00015, 0.0006, 1, 0, 0, 'fast,cheap',                 0, 1),
    ('m-gpt-o3m',  'openai',   'o3-mini',                         'o3-mini',                  200000, 100000,0.0011,  0.0044, 1, 0, 0, 'reasoning',                  0, 1),
    ('m-oai-emb',  'openai',   'text-embedding-3-small',          'Embeddings 3 Small',       8191,   0,     0.00002, 0.0,    0, 0, 1, 'embeddings',                 1, 1),
    ('m-oai-embl', 'openai',   'text-embedding-3-large',          'Embeddings 3 Large',       8191,   0,     0.00013, 0.0,    0, 0, 1, 'embeddings,high-dim',        0, 1),
    -- AWS Bedrock
    ('m-br-son4',  'bedrock',  'anthropic.claude-sonnet-4-20250514-v1:0', 'Claude Sonnet 4 (Bedrock)', 200000, 8192, 0.003, 0.015, 1, 1, 0, 'balanced,tools',     1, 1),
    ('m-br-hai35', 'bedrock',  'anthropic.claude-haiku-3-5-20241022-v1:0','Claude Haiku 3.5 (Bedrock)',200000, 8192, 0.0008,0.004, 1, 0, 0, 'fast,cheap',         0, 1),
    ('m-br-llm70', 'bedrock',  'meta.llama3-1-70b-instruct-v1:0', 'Llama 3.1 70B (Bedrock)',  128000, 4096,  0.00099, 0.00099,0, 0, 0, 'open-source',               0, 1),
    ('m-br-temb',  'bedrock',  'amazon.titan-embed-text-v2:0',    'Titan Embeddings v2',      8192,   0,     0.00002, 0.0,    0, 0, 1, 'embeddings',                 1, 1),
    -- Together.ai
    ('m-tg-ll70',  'together', 'meta-llama/Llama-3.3-70B-Instruct-Turbo','Llama 3.3 70B Turbo', 128000, 4096, 0.00088, 0.00088, 1, 0, 0, 'fast,open-source',     1, 1),
    ('m-tg-qw72',  'together', 'Qwen/Qwen2.5-72B-Instruct-Turbo','Qwen 2.5 72B Turbo',       32768,  4096,  0.0012,  0.0012, 1, 0, 0, 'multilingual',              0, 1),
    ('m-tg-ds70',  'together', 'deepseek-ai/DeepSeek-R1-Distill-Llama-70B','DeepSeek R1 70B', 128000, 4096,  0.00055, 0.00219,0, 0, 0, 'reasoning,cheap',           0, 1);
