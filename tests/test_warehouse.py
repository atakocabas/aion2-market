"""Warehouse (container 15): stored next to the bag at login, kept current during play, shown on the
inventory page as bag, warehouse or both."""
import json
import struct

from test_dashboard import _req, server  # noqa: F401  (pytest fixture)
from test_inventory_live import FIX, KEYS, MANIFEST, NOW, _bin, _login, _store

from aion2market import dashboard
from aion2market import inventory as inv
from aion2market.store import Store

WH = str(inv.CONTAINER_WAREHOUSE)
A, B = 610610015, 510716014


def _rec(op: int, n: int, key: int, count: int, container: int) -> bytes:
    sid = struct.pack("<II", 0x0D5000 + n, 0x4A00)
    return bytes([op, 0]) + sid + struct.pack("<IQBH", key, count, container, 7) + bytes(14)


def _msg(*records: bytes) -> bytes:
    return bytes([len(records)]) + b"".join(records) + b"\x00"


def _warehouse_ts(s: Store) -> set[float]:
    return {ts for (ts,) in s.db.execute("SELECT DISTINCT ts FROM warehouse")}


def test_constant_matches_the_fixture_containers():
    assert inv.CONTAINER_WAREHOUSE == 15 and WH in MANIFEST["login"]["totals"]


def test_login_stores_bag_and_warehouse():
    s = _store()
    game, conn = inv.GameTracker(s), inv.GameConnection()
    t = MANIFEST["login"]["t"]
    game.on_frame(conn, inv.INVENTORY_OPCODE, _login(), t)
    assert s.latest_inventory() == (t, MANIFEST["login"]["totals"]["1"])
    assert s.latest_warehouse() == (t, MANIFEST["login"]["totals"][WH])


def test_replaying_the_session_ends_at_the_final_warehouse_totals():
    s = _store()
    game, conn = inv.GameTracker(s), inv.GameConnection()
    login_t = MANIFEST["login"]["t"]
    s.set_warehouse(login_t - 86400, {"510716014": 1})                 # an earlier session's snapshot
    game.on_frame(conn, inv.INVENTORY_OPCODE, _login(), login_t)
    # the frame times at which the warehouse changed, read independently with the pure functions
    stacks, last_change = inv.parse_login(_login(), KEYS), login_t
    for f in MANIFEST["changes"]:
        before = inv.totals(stacks, inv.CONTAINER_WAREHOUSE)
        inv.apply_changes(stacks, inv.parse_changes(_bin(f["file"])), KEYS)
        if inv.totals(stacks, inv.CONTAINER_WAREHOUSE) != before:
            last_change = f["t"]
        game.on_frame(conn, inv.CHANGE_OPCODE, _bin(f["file"]), f["t"])
    final = MANIFEST["final_totals"][WH]
    assert all(c < inv.MAX_COUNT for c in final.values())
    assert final != MANIFEST["login"]["totals"][WH]                       # the session did move things
    assert last_change != login_t
    assert s.latest_warehouse() == (last_change, final)
    assert _warehouse_ts(s) == {login_t - 86400, last_change}          # login snapshot updated in place
    assert s.latest_inventory() == (MANIFEST["last_bag_change_t"], MANIFEST["final_totals"]["1"])


def _seeded_tracker():
    s = Store(":memory:")
    s.add_snapshots(NOW, 12306, [(str(A), 1.0, 1), (str(B), 1.0, 1)])
    game, conn = inv.GameTracker(s), inv.GameConnection()
    conn.stacks = {}
    game.on_frame(conn, inv.CHANGE_OPCODE, _msg(_rec(inv.ADD, 1, A, 5, 1), _rec(inv.ADD, 2, A, 9, 15)), NOW)
    return s, game, conn


def test_bag_only_change_leaves_the_warehouse_snapshot_alone():
    s, game, conn = _seeded_tracker()
    assert s.latest_warehouse() == (NOW, {str(A): 9})
    game.on_frame(conn, inv.CHANGE_OPCODE, _msg(_rec(inv.UPDATE, 1, A, 7, 1)), NOW + 5)
    assert s.latest_inventory() == (NOW + 5, {str(A): 7})
    assert s.latest_warehouse() == (NOW, {str(A): 9})


def test_warehouse_only_change_leaves_the_bag_snapshot_alone():
    s, game, conn = _seeded_tracker()
    game.on_frame(conn, inv.CHANGE_OPCODE, _msg(_rec(inv.ADD, 3, B, 2, 15)), NOW + 5)
    assert s.latest_warehouse() == (NOW + 5, {str(A): 9, str(B): 2})
    assert s.latest_inventory() == (NOW, {str(A): 5})


def test_warehouse_store_methods():
    s = Store(":memory:")
    assert s.latest_warehouse() == (None, {})
    s.update_warehouse(NOW, {"a": 1})                                   # empty table: just inserts
    assert s.latest_warehouse() == (NOW, {"a": 1})
    s.set_warehouse(NOW + 10, {"a": 2, "b": 1})
    s.update_warehouse(NOW + 20, {"b": 3})
    assert s.latest_warehouse() == (NOW + 20, {"b": 3})
    assert _warehouse_ts(s) == {NOW, NOW + 20}
    assert s.latest_inventory() == (None, {})                           # tables are separate


def test_snapshot_helpers_refuse_other_tables():
    s = Store(":memory:")
    for bad in ("meta", "inventory; DROP TABLE meta", ""):
        try:
            s._latest_snapshot(bad)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_import_run_stores_the_warehouse(tmp_path, monkeypatch):
    from aion2market import report
    s = _store()
    t = MANIFEST["login"]["t"]

    class F:
        opcode, payload = inv.INVENTORY_OPCODE, (FIX / MANIFEST["login"]["file"]).read_bytes()
    monkeypatch.setattr(report, "load_frames", lambda run: [(t, None, F)])
    assert inv.import_run(s, tmp_path) == (t, MANIFEST["login"]["totals"]["1"])
    assert s.latest_warehouse() == (t, MANIFEST["login"]["totals"][WH])


# --- inventory_view places ---------------------------------------------------------------------------

def _view_store() -> Store:
    s = Store(":memory:")
    s.add_snapshots(NOW - 60, 12306, [("x", 100.0, 5), ("y", 50.0, 5), ("z", 10.0, 5)])
    s.set_inventory(NOW - 30, {"x": 2, "y": 1})
    s.set_warehouse(NOW - 20, {"x": 3, "z": 4, "gone": 1})
    return s


def test_inventory_view_places():
    s = _view_store()
    bag = dashboard.inventory_view(s, 12306)
    assert bag["place"] == "bag" and bag["ts"] == NOW - 30
    assert bag["bag_ts"] == NOW - 30 and bag["warehouse_ts"] == NOW - 20
    assert {i["item_key"]: i["owned"] for i in bag["items"]} == {"x": 2, "y": 1}
    assert dashboard.inventory_view(s, 12306, place="bag") == bag

    wh = dashboard.inventory_view(s, 12306, place="warehouse")
    assert wh["place"] == "warehouse" and wh["ts"] == NOW - 20
    assert {i["item_key"]: i["owned"] for i in wh["items"]} == {"x": 3, "z": 4}
    assert [u["item_key"] for u in wh["unpriced"]] == ["gone"]

    both = dashboard.inventory_view(s, 12306, place="all")
    assert both["place"] == "all" and both["ts"] == NOW - 20
    by = {i["item_key"]: i for i in both["items"]}
    assert {k: i["owned"] for k, i in by.items()} == {"x": 5, "y": 1, "z": 4}
    # the advice is the same per item whichever place it is counted in
    for k, i in by.items():
        src = next(r for r in (bag["items"] + wh["items"]) if r["item_key"] == k)
        assert (i["signal"], i["why"], i["suggest_price"]) == (src["signal"], src["why"], src["suggest_price"])
    assert both["total_value"] == sum(i["value_net"] for i in both["items"])

    assert dashboard.inventory_view(s, 12306, place="bogus")["place"] == "bag"


def test_inventory_view_without_a_warehouse():
    s = Store(":memory:")
    s.set_inventory(NOW, {"x": 1})
    wh = dashboard.inventory_view(s, place="warehouse")
    assert wh["ts"] is None and wh["warehouse_ts"] is None and wh["items"] == [] and wh["unpriced"] == []
    assert dashboard.inventory_view(s, place="all")["ts"] == NOW


def test_api_inventory_place_parameter(server):  # noqa: F811
    port, path = server
    s = Store(path)
    s.set_inventory(NOW - 30, {"1": 2})
    s.set_warehouse(NOW - 20, {"1": 5})
    s.close()

    def get(q):
        status, body = _req(port, "GET", "/api/inventory" + q)
        assert status == 200
        return json.loads(body)
    owned = lambda v: {i["item_key"]: i["owned"] for i in v["items"]}   # noqa: E731
    assert get("")["place"] == "bag" and owned(get("")) == {"1": 2}
    assert get("?place=warehouse")["place"] == "warehouse" and owned(get("?place=warehouse")) == {"1": 5}
    assert owned(get("?place=all")) == {"1": 7}
    bogus = get("?place=bogus")
    assert bogus["place"] == "bag" and owned(bogus) == {"1": 2} and bogus["warehouse_ts"] == NOW - 20
