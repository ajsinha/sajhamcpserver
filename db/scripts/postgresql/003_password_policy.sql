-- ============================================================================
-- SAJHA MCP Server — Password policy (PostgreSQL)
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
-- Idempotent: ADD COLUMN IF NOT EXISTS, and the UPDATE re-flags only the seed password.
-- ============================================================================

ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- The seeded admin/admin123 must be changed: flag it while the seed hash is still in place.
UPDATE users SET must_change_password = TRUE
 WHERE user_id = 'admin'
   AND password_hash = '$2b$12$/gOLIbLgjm3zLsDBoslN7erBkWLnS3dVe5SfQ0vptnsHclfHzTCMW';
