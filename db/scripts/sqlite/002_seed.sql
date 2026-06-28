-- ============================================================================
-- SAJHA MCP Server v5.1.0 — Seed Data (SQLite)
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
-- Idempotent: INSERT OR IGNORE.
-- IMPORTANT: Change the admin password on first login.
-- ============================================================================

INSERT OR IGNORE INTO roles (id, name, description, is_system) VALUES
    ('r-admin', 'admin', 'Full system access', 1),
    ('r-user', 'user', 'Standard tool access', 1),
    ('r-viewer', 'viewer', 'Read-only access', 1),
    ('r-developer', 'developer', 'Developer access — MCP Studio', 1);

INSERT OR IGNORE INTO users (id, user_id, user_name, email, password_hash, enabled)
VALUES ('u-admin', 'admin', 'Administrator', 'admin@sajha.local',
        '$2b$12$/gOLIbLgjm3zLsDBoslN7erBkWLnS3dVe5SfQ0vptnsHclfHzTCMW', 1);

INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES ('u-admin', 'r-admin');

INSERT OR IGNORE INTO permissions (id, role_id, resource_type, resource_name, actions) VALUES
    ('p-admin-all', 'r-admin', '*', '*', '*'),
    ('p-user-tools', 'r-user', 'tool', '*', 'execute,read'),
    ('p-viewer-read', 'r-viewer', 'tool', '*', 'read'),
    ('p-dev-studio', 'r-developer', 'studio', '*', '*'),
    ('p-dev-tools', 'r-developer', 'tool', '*', 'execute,read,create');
