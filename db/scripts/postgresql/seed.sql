-- ============================================================================
-- SAJHA MCP Server: default roles, permissions and admin user (PostgreSQL)
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
--
-- Run once, on a new database, right after schema.sql:
--
--   psql -v ON_ERROR_STOP=1 -h HOST -U USER -d DBNAME -f db/scripts/postgresql/seed.sql
--
-- Idempotent (ON CONFLICT DO NOTHING) and atomic. The admin's password is admin123
-- and is flagged must_change_password: SAJHA makes the first sign-in change it.
-- Running it again re-creates any of these rows that were deleted, so do not re-run
-- it on a database in use.
-- ============================================================================

BEGIN;

INSERT INTO roles (id, name, description, is_system) VALUES
    ('r-admin', 'admin', 'Full system access', TRUE),
    ('r-user', 'user', 'Standard tool access', TRUE),
    ('r-viewer', 'viewer', 'Read-only access', TRUE),
    ('r-developer', 'developer', 'Developer access — MCP Studio', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO users (id, user_id, user_name, email, password_hash, enabled, must_change_password)
VALUES ('u-admin', 'admin', 'Administrator', 'admin@sajha.local',
        '$2b$12$/gOLIbLgjm3zLsDBoslN7erBkWLnS3dVe5SfQ0vptnsHclfHzTCMW', TRUE, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id) VALUES ('u-admin', 'r-admin')
ON CONFLICT DO NOTHING;

INSERT INTO permissions (id, role_id, resource_type, resource_name, actions) VALUES
    ('p-admin-all', 'r-admin', '*', '*', '*'),
    ('p-user-tools', 'r-user', 'tool', '*', 'execute,read'),
    ('p-viewer-read', 'r-viewer', 'tool', '*', 'read'),
    ('p-dev-studio', 'r-developer', 'studio', '*', '*'),
    ('p-dev-tools', 'r-developer', 'tool', '*', 'execute,read,create')
ON CONFLICT DO NOTHING;

COMMIT;
