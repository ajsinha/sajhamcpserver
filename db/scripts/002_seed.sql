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
