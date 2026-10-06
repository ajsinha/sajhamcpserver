-- ============================================================================
-- SAJHA MCP Server — Password policy (SQLite)
-- Copyright All rights Reserved 2025-2030, Ashutosh Sinha
-- Idempotent: the ALTER fails harmlessly when the column exists (the script
-- runner skips failed statements), and the UPDATE re-flags only the seed password.
-- ============================================================================

ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;

-- The seeded admin/admin123 must be changed: flag it while the seed hash is still in place.
UPDATE users SET must_change_password = 1
 WHERE user_id = 'admin'
   AND password_hash = '$2b$12$/gOLIbLgjm3zLsDBoslN7erBkWLnS3dVe5SfQ0vptnsHclfHzTCMW';
