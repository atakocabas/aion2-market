-- Only for a database created before self-registration (schema.sql already has these columns).
--   npx wrangler d1 execute aion2-market --remote --file=migrate-001.sql
-- Then run schema.sql again for the new tables.
ALTER TABLE contributors ADD COLUMN auto INTEGER NOT NULL DEFAULT 0;
ALTER TABLE contributors ADD COLUMN window_start REAL NOT NULL DEFAULT 0;
ALTER TABLE contributors ADD COLUMN window_rows INTEGER NOT NULL DEFAULT 0;
