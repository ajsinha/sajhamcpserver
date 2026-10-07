-- ============================================================================
-- SAJHA MCP Server: default roles, permissions and admin user (SQLite)
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
--
-- SAJHA runs this itself when it creates a new SQLite database (never on an
-- existing one, so a deleted admin stays deleted). By hand:
--
--   sqlite3 data/sajha.db < db/scripts/sqlite/seed.sql
--
-- Idempotent (INSERT OR IGNORE) and atomic. The admin's password is admin123
-- and is flagged must_change_password: SAJHA makes the first sign-in change it.
--
-- Studio permissions (resource_type studio) name the creator they open: resource_name
-- '*' (studio:*) opens every creator, 'llm' (studio:llm) only the LLM tool creator, and so on
-- (docs/security/Security Model.md section 5). They are data: add rows to give a role more.
-- ============================================================================

BEGIN;

INSERT OR IGNORE INTO roles (id, name, description, is_system) VALUES
    ('r-admin', 'admin', 'Full system access', 1),
    ('r-user', 'user', 'Standard tool access', 1),
    ('r-viewer', 'viewer', 'Read-only access', 1),
    ('r-developer', 'developer', 'Developer access — MCP Studio', 1),
    ('r-llm-author', 'llm_author', 'MCP Studio: LLM tools only', 1);

INSERT OR IGNORE INTO users (id, user_id, user_name, email, password_hash, enabled, must_change_password)
VALUES ('u-admin', 'admin', 'Administrator', 'admin@sajha.local',
        '$2b$12$/gOLIbLgjm3zLsDBoslN7erBkWLnS3dVe5SfQ0vptnsHclfHzTCMW', 1, 1);

INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES ('u-admin', 'r-admin');

INSERT OR IGNORE INTO permissions (id, role_id, resource_type, resource_name, actions) VALUES
    ('p-admin-all', 'r-admin', '*', '*', '*'),
    ('p-user-tools', 'r-user', 'tool', '*', 'execute,read'),
    ('p-viewer-read', 'r-viewer', 'tool', '*', 'read'),
    ('p-dev-studio', 'r-developer', 'studio', '*', '*'),
    ('p-dev-tools', 'r-developer', 'tool', '*', 'execute,read,create'),
    ('p-llm-studio', 'r-llm-author', 'studio', 'llm', 'use'),
    ('p-llm-tools', 'r-llm-author', 'tool', '*', 'execute,read');

COMMIT;
