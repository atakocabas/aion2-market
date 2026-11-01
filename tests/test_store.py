import sqlite3

from aion2market.store import Store


def test_old_database_gets_columns_indexes_and_wal(tmp_path):
    path = tmp_path / "market.db"
    # price_snapshots as first released: no origin column yet
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE price_snapshots (ts REAL NOT NULL, server_id INTEGER NOT NULL, item_key TEXT NOT NULL, "
                "min_unit_price REAL NOT NULL, sale_count INTEGER NOT NULL, PRIMARY KEY (item_key, server_id, ts))")
    old.execute("INSERT INTO price_snapshots VALUES (1.0, 12306, '1', 100.0, 5)")
    old.commit()
    old.close()

    s = Store(path)
    assert s.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert s.home_server() == 12306                   # old rows count as this computer's own
    plan = s.db.execute("EXPLAIN QUERY PLAN SELECT item_key, ts, min_unit_price, sale_count FROM price_snapshots "
                        "WHERE server_id = ? ORDER BY ts", (12306,)).fetchall()
    assert "COVERING INDEX price_snapshots_server_ts" in plan[0][3]
    s.close()
