-- Shared Aion 2 market price store (Cloudflare D1).
-- Apply with: npx wrangler d1 execute aion2-market --remote --file=schema.sql
-- A database made before self-registration also needs migrate-001.sql (once).

-- Uploaders: invited by the owner (auto = 0) or registered by the app itself (auto = 1).
-- Only a SHA-256 of each key is stored. window_* count rows uploaded in the current hour.
CREATE TABLE IF NOT EXISTS contributors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    active       INTEGER NOT NULL DEFAULT 1,
    created_ts   REAL NOT NULL,
    last_seen_ts REAL,
    auto         INTEGER NOT NULL DEFAULT 0,
    window_start REAL NOT NULL DEFAULT 0,
    window_rows  INTEGER NOT NULL DEFAULT 0
);

-- Self-registrations per day and caller, for the registration limit. The caller is a salted
-- SHA-256 of its IP (salt: ADMIN_TOKEN), never the IP itself; rows from earlier days are deleted.
CREATE TABLE IF NOT EXISTS registrations (
    day     TEXT NOT NULL,
    caller  TEXT NOT NULL,
    count   INTEGER NOT NULL,
    PRIMARY KEY (day, caller)
);

-- Typical price per item, a slow average of accepted uploads. Uploads far from it are rejected.
CREATE TABLE IF NOT EXISTS item_ref (
    server_id  INTEGER NOT NULL,
    item_key   TEXT NOT NULL,
    ref_price  REAL NOT NULL,
    samples    INTEGER NOT NULL,
    updated_ts REAL NOT NULL,
    PRIMARY KEY (server_id, item_key)
);

-- Lowest unit price per item from /trade/v1.0/sales/valid/summary/min_unit_price.
-- seq is the download cursor.
CREATE TABLE IF NOT EXISTS snapshots (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id      INTEGER NOT NULL,
    item_key       TEXT NOT NULL,
    ts             REAL NOT NULL,
    min_unit_price REAL NOT NULL,
    sale_count     INTEGER NOT NULL,
    contributor_id INTEGER NOT NULL,
    received_ts    REAL NOT NULL,
    UNIQUE (server_id, item_key, ts)
);
CREATE INDEX IF NOT EXISTS snapshots_item ON snapshots (server_id, item_key, ts);
CREATE INDEX IF NOT EXISTS snapshots_contributor ON snapshots (contributor_id);

-- Individual listings from /trade/v1.0/sales/valid/pages (no seller information exists in them).
CREATE TABLE IF NOT EXISTS listings (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id      INTEGER NOT NULL,
    item_key       TEXT NOT NULL,
    ts             REAL NOT NULL,
    sale_id        TEXT NOT NULL,
    quantity       INTEGER NOT NULL,
    sale_price     INTEGER NOT NULL,
    unit_price     REAL NOT NULL,
    effective_from TEXT,
    effective_to   TEXT,
    grade_id       INTEGER,
    category_id    INTEGER,
    contributor_id INTEGER NOT NULL,
    received_ts    REAL NOT NULL,
    UNIQUE (sale_id, ts)
);
CREATE INDEX IF NOT EXISTS listings_contributor ON listings (contributor_id);

CREATE TABLE IF NOT EXISTS servers (
    server_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL
);

-- Official item data (names, grades, icons) one user's app fetched from NC's public item API, so users
-- whose network can't reach it still get names. The first upload per item is kept. seq is the download cursor.
CREATE TABLE IF NOT EXISTS item_info (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    item_key       TEXT NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    grade          TEXT,
    grade_name     TEXT,
    category       TEXT,
    type           TEXT,
    icon           TEXT,
    contributor_id INTEGER NOT NULL,
    received_ts    REAL NOT NULL
);
