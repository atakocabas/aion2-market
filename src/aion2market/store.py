"""SQLite storage for market observations.

Timestamps are Unix seconds taken from the server's ``loaded`` field when the
response has one, so replaying the same capture twice inserts nothing new.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_key TEXT PRIMARY KEY,
    name     TEXT NOT NULL
);
-- min_unit_price/sale_count per item, from /sales/valid/summary/min_unit_price
CREATE TABLE IF NOT EXISTS price_snapshots (
    ts             REAL NOT NULL,
    server_id      INTEGER NOT NULL,
    item_key       TEXT NOT NULL,
    min_unit_price REAL NOT NULL,
    sale_count     INTEGER NOT NULL,
    PRIMARY KEY (item_key, server_id, ts)
);
-- individual listings as seen on one page fetch, from /sales/valid/pages
CREATE TABLE IF NOT EXISTS listings (
    ts             REAL NOT NULL,
    server_id      INTEGER NOT NULL,
    item_key       TEXT NOT NULL,
    sale_id        TEXT NOT NULL,
    quantity       INTEGER NOT NULL,
    sale_price     INTEGER NOT NULL,
    unit_price     REAL NOT NULL,
    effective_from TEXT,
    effective_to   TEXT,
    grade_id       INTEGER,
    category_id    INTEGER,
    PRIMARY KEY (sale_id, ts)
);
CREATE INDEX IF NOT EXISTS listings_item_ts ON listings (item_key, ts);
-- items the user follows; target_price is a unit price to alert at or below (Faz 4)
CREATE TABLE IF NOT EXISTS watchlist (
    item_key     TEXT PRIMARY KEY,
    target_price REAL,
    added_ts     REAL NOT NULL
);
-- raw /trade/v1.0/sales/ exchanges (bodies only, never headers), for re-parsing later
CREATE TABLE IF NOT EXISTS responses (
    ts      REAL NOT NULL,
    path    TEXT NOT NULL,
    request TEXT NOT NULL,
    status  INTEGER NOT NULL,
    body    TEXT NOT NULL,
    PRIMARY KEY (ts, path, request)
);
-- official item data (tw.ncsoft.com gameconst API); found = 0 means the API didn't know the key
CREATE TABLE IF NOT EXISTS item_info (
    item_key   TEXT PRIMARY KEY,
    found      INTEGER NOT NULL,
    name       TEXT,
    grade      TEXT,
    grade_name TEXT,
    category   TEXT,
    type       TEXT,
    icon       TEXT,
    fetched_ts REAL NOT NULL
);
-- names/categories from aion2.exchange, used only for items NC's data doesn't know
CREATE TABLE IF NOT EXISTS exchange_names (
    item_key   TEXT PRIMARY KEY,
    name       TEXT,
    category   TEXT,
    updated_ts REAL NOT NULL
);
-- notifications sent for watched items
CREATE TABLE IF NOT EXISTS alerts (
    ts           REAL NOT NULL,
    item_key     TEXT NOT NULL,
    price        REAL NOT NULL,
    target_price REAL NOT NULL
);
-- market servers (the trade API's game_server_id); names are given by people
CREATE TABLE IF NOT EXISTS servers (
    server_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL
);
-- price range per time bucket (from aion2.exchange history): ts is the bucket start, span its length
CREATE TABLE IF NOT EXISTS price_ranges (
    server_id INTEGER NOT NULL,
    item_key  TEXT NOT NULL,
    ts        REAL NOT NULL,
    span      REAL NOT NULL,
    low       REAL NOT NULL,
    high      REAL NOT NULL,
    avg       REAL,
    close     REAL NOT NULL,
    listings  INTEGER,
    samples   INTEGER,
    PRIMARY KEY (server_id, item_key, ts, span)
);
-- the character's inventory as the game sent it at each login (opcode 0x5611)
CREATE TABLE IF NOT EXISTS inventory (
    ts       REAL NOT NULL,
    item_key TEXT NOT NULL,
    count    INTEGER NOT NULL,
    PRIMARY KEY (ts, item_key)
);
-- small key/value state, e.g. sync cursors
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Columns added after a table was first released: (table, column, definition).
MIGRATIONS = [
    # unit price of the last alert; cleared when the price goes back above target
    ("watchlist", "last_alert_price", "REAL"),
    # 'local': seen by this computer's game client; 'shared': downloaded from the shared store
    ("price_snapshots", "origin", "TEXT NOT NULL DEFAULT 'local'"),
    ("listings", "origin", "TEXT NOT NULL DEFAULT 'local'"),
]

# Made after MIGRATIONS, since they use columns older databases only get there.
INDEXES = """
-- one server's whole series in time order (the UI's main query), read from the index alone
CREATE INDEX IF NOT EXISTS price_snapshots_server_ts
    ON price_snapshots (server_id, ts, item_key, min_unit_price, sale_count, origin);
-- this computer's own newest snapshot (home_server)
CREATE INDEX IF NOT EXISTS price_snapshots_origin_ts ON price_snapshots (origin, ts);
"""


class Store:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The service, its background threads, the UI and the MCP server share one file.
        self.db = sqlite3.connect(str(path), timeout=15)
        if str(path) != ":memory:":
            # WAL lets the UI and MCP server read while the service writes; the mode stays with the file.
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        for table, column, definition in MIGRATIONS:
            cols = {r[1] for r in self.db.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        self.db.executescript(INDEXES)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def add_response(self, ts: float, path: str, request: str, status: int, body: str) -> bool:
        """Returns False if this exact exchange is already stored."""
        cur = self.db.execute("INSERT OR IGNORE INTO responses VALUES (?, ?, ?, ?, ?)",
                              (ts, path, request, status, body))
        self.db.commit()
        return cur.rowcount == 1

    def add_snapshots(self, ts: float, server_id: int, rows: list[tuple[str, float, int]],
                      origin: str = "local") -> int:
        cur = self.db.executemany(
            "INSERT OR IGNORE INTO price_snapshots (ts, server_id, item_key, min_unit_price, sale_count, origin) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(ts, server_id, key, price, count, origin) for key, price, count in rows])
        self.db.commit()
        return cur.rowcount

    def add_listings(self, ts: float, server_id: int, sales: list[dict], origin: str = "local") -> int:
        cur = self.db.executemany(
            "INSERT OR IGNORE INTO listings (ts, server_id, item_key, sale_id, quantity, sale_price, unit_price, "
            "effective_from, effective_to, grade_id, category_id, origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(ts, server_id, s["game_item_key"], s["sale_id"], int(s["game_item_quantity"]),
              int(s["sale_price"]), float(s["unit_price"]), s.get("effective_from"), s.get("effective_to"),
              _int(s.get("grade_id")), _int(s.get("category_id")), origin) for s in sales])
        self.db.commit()
        return cur.rowcount

    def home_server(self) -> int | None:
        """The market server this computer's own game client used most recently."""
        row = self.db.execute("SELECT server_id FROM price_snapshots WHERE origin = 'local' "
                              "ORDER BY ts DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def servers(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT p.server_id, s.name, COUNT(DISTINCT p.item_key), MAX(p.ts), "
            "SUM(p.origin = 'local') > 0 FROM price_snapshots p LEFT JOIN servers s USING (server_id) "
            "GROUP BY p.server_id ORDER BY MAX(p.ts) DESC").fetchall()
        return [{"server_id": sid, "name": name, "items": n, "latest": ts, "mine": bool(mine)}
                for sid, name, n, ts, mine in rows]

    def set_server_name(self, server_id: int, name: str) -> None:
        self.db.execute("INSERT INTO servers VALUES (?, ?) ON CONFLICT(server_id) DO UPDATE SET name = excluded.name",
                        (server_id, name))
        self.db.commit()

    def add_ranges(self, server_id: int, item_key: str, rows: list[tuple]) -> int:
        """rows: (ts, span, low, high, avg, close, listings, samples); a re-fetched bucket is replaced."""
        cur = self.db.executemany(
            "INSERT OR REPLACE INTO price_ranges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(server_id, item_key, *r) for r in rows])
        self.db.commit()
        return cur.rowcount

    def ranges(self, item_key: str, server_id: int, since: float = 0) -> list[tuple]:
        return self.db.execute(
            "SELECT ts, span, low, high, avg, close, listings FROM price_ranges "
            "WHERE item_key = ? AND server_id = ? AND ts >= ? ORDER BY ts", (item_key, server_id, since)).fetchall()

    def set_inventory(self, ts: float, items: dict[str, int]) -> None:
        self.db.executemany("INSERT OR REPLACE INTO inventory VALUES (?, ?, ?)",
                            [(ts, k, c) for k, c in items.items()])
        self.db.commit()

    def latest_inventory(self) -> tuple[float | None, dict[str, int]]:
        ts = self.db.execute("SELECT MAX(ts) FROM inventory").fetchone()[0]
        if ts is None:
            return None, {}
        return ts, dict(self.db.execute("SELECT item_key, count FROM inventory WHERE ts = ?", (ts,)).fetchall())

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        self.db.commit()

    def set_name(self, item_key: str, name: str) -> None:
        self.db.execute("INSERT INTO items VALUES (?, ?) ON CONFLICT(item_key) DO UPDATE SET name = excluded.name",
                        (item_key, name))
        self.db.commit()

    def clear_name(self, item_key: str) -> None:
        self.db.execute("DELETE FROM items WHERE item_key = ?", (item_key,))
        self.db.commit()

    def name(self, item_key: str) -> str | None:
        """The user's name for the item, else NC's official one, else aion2.exchange's."""
        row = self.db.execute(
            "SELECT COALESCE((SELECT name FROM items WHERE item_key = ?), "
            "(SELECT name FROM item_info WHERE item_key = ? AND found = 1), "
            "(SELECT name FROM exchange_names WHERE item_key = ?))", (item_key,) * 3).fetchone()
        return row[0]

    def resolve(self, key_or_name: str) -> list[str]:
        """Item keys matching a key or a (case-insensitive, partial) name from any source."""
        if key_or_name.isdigit():
            return [key_or_name]
        pattern = f"%{key_or_name}%"
        rows = self.db.execute(
            "SELECT item_key, name FROM items WHERE name LIKE ?1 "
            "UNION SELECT item_key, name FROM item_info WHERE found = 1 AND name LIKE ?1 "
            "AND item_key NOT IN (SELECT item_key FROM items) "
            "UNION SELECT item_key, name FROM exchange_names WHERE name LIKE ?1 "
            "AND item_key NOT IN (SELECT item_key FROM items) "
            "AND item_key NOT IN (SELECT item_key FROM item_info WHERE found = 1) ORDER BY 2", (pattern,)).fetchall()
        return [r[0] for r in rows]

    def set_exchange_names(self, rows: list[tuple[str, str | None, str | None]], now: float) -> None:
        """(item_key, name, category); a missing name or category never erases a known one."""
        self.db.executemany(
            "INSERT INTO exchange_names VALUES (?, ?, ?, ?) ON CONFLICT(item_key) DO UPDATE SET "
            "name = COALESCE(excluded.name, name), category = COALESCE(excluded.category, category), "
            "updated_ts = excluded.updated_ts", [(k, n, c, now) for k, n, c in rows])
        self.db.commit()

    def set_item_info(self, item_key: str, info: dict | None, now: float) -> None:
        """Store official item data; ``None`` records that the official source doesn't know the item."""
        info = info or {}
        self.db.execute(
            "INSERT OR REPLACE INTO item_info VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item_key, 1 if info else 0, info.get("name"), info.get("grade"), info.get("gradeName"),
             info.get("categoryName"), info.get("type"), info.get("icon"), now))
        self.db.commit()

    def item_info(self) -> dict[str, dict]:
        """NC's official data per item; items NC doesn't know fall back to aion2.exchange's name and category."""
        rows = self.db.execute(
            "SELECT item_key, name, grade, grade_name, category, type, icon FROM item_info WHERE found = 1")
        info = {k: {"name": n, "grade": g, "grade_name": gn, "category": c, "type": t, "icon": i, "source": "nc"}
                for k, n, g, gn, c, t, i in rows}
        for k, n, c in self.db.execute("SELECT item_key, name, category FROM exchange_names"):
            if k not in info and (n or c):
                info[k] = {"name": n, "grade": None, "grade_name": None, "category": c, "type": None,
                           "icon": None, "source": "aion2.exchange"}
        return info

    def keys_missing_info(self, retry_before: float) -> list[str]:
        """Seen item keys never looked up, or not found by a lookup older than ``retry_before``."""
        rows = self.db.execute(
            "SELECT DISTINCT item_key FROM (SELECT item_key FROM price_snapshots UNION SELECT item_key FROM listings) "
            "WHERE item_key NOT IN (SELECT item_key FROM item_info WHERE found = 1 OR fetched_ts >= ?) "
            "ORDER BY item_key", (retry_before,)).fetchall()
        return [r[0] for r in rows]

    # Price queries take an optional server_id; None means every server.
    _SERVER = "(? IS NULL OR server_id = ?)"

    def latest_snapshot(self, item_key: str, server_id: int | None = None) -> tuple[float, float, int] | None:
        return self.db.execute(
            f"SELECT ts, min_unit_price, sale_count FROM price_snapshots WHERE item_key = ? AND {self._SERVER} "
            "ORDER BY ts DESC LIMIT 1", (item_key, server_id, server_id)).fetchone()

    def latest_listings(self, item_key: str, server_id: int | None = None) -> tuple[float, list[tuple[int, int, float]]]:
        """(ts, [(quantity, sale_price, unit_price), ...] by unit price) of the newest page fetch."""
        row = self.db.execute(f"SELECT MAX(ts), MAX(server_id) FROM listings WHERE item_key = ? AND {self._SERVER}",
                              (item_key, server_id, server_id)).fetchone()
        if row[0] is None:
            return 0.0, []
        rows = self.db.execute(
            "SELECT quantity, sale_price, unit_price FROM listings WHERE item_key = ? AND ts = ? "
            f"AND {self._SERVER} ORDER BY unit_price", (item_key, row[0], server_id, server_id)).fetchall()
        return row[0], rows

    def named_items(self) -> list[tuple[str, str]]:
        return self.db.execute("SELECT item_key, name FROM items ORDER BY name").fetchall()

    def snapshot_history(self, item_key: str, since: float,
                         server_id: int | None = None) -> list[tuple[float, float, int]]:
        return self.db.execute(
            "SELECT ts, min_unit_price, sale_count FROM price_snapshots WHERE item_key = ? AND ts >= ? "
            f"AND {self._SERVER} ORDER BY ts", (item_key, since, server_id, server_id)).fetchall()

    def listing_history(self, item_key: str, since: float,
                        server_id: int | None = None) -> list[tuple[float, int, float, int | None]]:
        """Per page fetch: (ts, listing count, cheapest unit price, cheapest single-unit sale price)."""
        return self.db.execute(
            "SELECT ts, COUNT(*), MIN(unit_price), MIN(CASE WHEN quantity = 1 THEN sale_price END) "
            f"FROM listings WHERE item_key = ? AND ts >= ? AND {self._SERVER} GROUP BY ts ORDER BY ts",
            (item_key, since, server_id, server_id)).fetchall()

    def watch(self, item_key: str, target_price: float | None, now: float) -> None:
        # A new target starts a fresh alert cycle.
        self.db.execute("INSERT INTO watchlist (item_key, target_price, added_ts) VALUES (?, ?, ?) "
                        "ON CONFLICT(item_key) DO UPDATE SET target_price = excluded.target_price, "
                        "last_alert_price = NULL",
                        (item_key, target_price, now))
        self.db.commit()

    def watch_state(self, item_key: str) -> tuple[float | None, float | None] | None:
        """(target_price, last_alert_price) or None if the item isn't watched."""
        return self.db.execute("SELECT target_price, last_alert_price FROM watchlist WHERE item_key = ?",
                               (item_key,)).fetchone()

    def set_last_alert(self, item_key: str, price: float | None) -> None:
        self.db.execute("UPDATE watchlist SET last_alert_price = ? WHERE item_key = ?", (price, item_key))
        self.db.commit()

    def add_alert(self, ts: float, item_key: str, price: float, target_price: float) -> None:
        self.db.execute("INSERT INTO alerts VALUES (?, ?, ?, ?)", (ts, item_key, price, target_price))
        self.db.commit()

    def recent_alerts(self, limit: int) -> list[tuple[float, str, float, float]]:
        return self.db.execute("SELECT ts, item_key, price, target_price FROM alerts ORDER BY ts DESC LIMIT ?",
                               (limit,)).fetchall()

    def unwatch(self, item_key: str) -> bool:
        cur = self.db.execute("DELETE FROM watchlist WHERE item_key = ?", (item_key,))
        self.db.commit()
        return cur.rowcount == 1

    def watchlist(self) -> list[tuple[str, float | None]]:
        return self.db.execute("SELECT item_key, target_price FROM watchlist ORDER BY added_ts").fetchall()


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
