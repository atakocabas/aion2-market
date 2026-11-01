-- Only for a database created before the second-key rule and the snapshot counter (schema.sql already has these).
--   npx wrangler d1 execute aion2-market --remote --file=migrate-002.sql
-- Run it once, before deploying the worker that uses the new columns.
ALTER TABLE contributors ADD COLUMN snapshots INTEGER NOT NULL DEFAULT 0;
UPDATE contributors SET snapshots = (SELECT COUNT(*) FROM snapshots s WHERE s.contributor_id = contributors.id);
ALTER TABLE item_ref ADD COLUMN first_contributor INTEGER;
ALTER TABLE item_ref ADD COLUMN multi INTEGER NOT NULL DEFAULT 0;
-- Typical prices that already reject outliers keep doing so; who sent them first isn't known.
UPDATE item_ref SET multi = 1 WHERE samples >= 3;
