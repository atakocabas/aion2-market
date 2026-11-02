-- Only for a database created before the usage statistics (schema.sql already has this table).
--   npx wrangler d1 execute aion2-market --remote --file=migrate-003.sql
-- Safe to run more than once; run it before deploying the worker that writes to it.
-- One row per key per UTC day it made any authenticated request; only keys are stored, no IPs.
CREATE TABLE IF NOT EXISTS activity (day TEXT NOT NULL, contributor_id INTEGER NOT NULL, PRIMARY KEY (day, contributor_id));
