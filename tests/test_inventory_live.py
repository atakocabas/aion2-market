"""Live inventory: login 0x5611 stacks kept up to date with 0x561b item change lists.

Fixtures are real server payloads of one login session (capture 20261029-050318, conn27) plus a few
frames of the next session (conn38). manifest.json holds what the research decoder read from them.
"""
import json
import struct
from collections import Counter
from pathlib import Path

import pytest

from aion2market import inventory as inv
from aion2market.store import Store

FIX = Path(__file__).parent / "fixtures" / "inventory"
MANIFEST = json.loads((FIX / "manifest.json").read_text())
KEYS = set(MANIFEST["known_keys"])
NOW = 1_800_000_000.0


def _bin(name: str) -> bytes:
    return (FIX / name).read_bytes()


def _login() -> bytes:
    return _bin(MANIFEST["login"]["file"])


def _rows(changes) -> list[list]:
    return [[op, sid.hex(), int(st.item_key), st.count, st.container] for op, sid, st in changes]


def _store() -> Store:
    s = Store(":memory:")
    s.add_snapshots(NOW, 12306, [(str(k), 1.0, 1) for k in KEYS])     # makes every fixture key a known key
    return s


# hand-built 0x561b messages: u8 n, then n x (u8 op | u8 ext | id8 | u32 key | u64 count | u8 container | u16 slot | tail)
def _id(n: int) -> bytes:
    return struct.pack("<II", 0x0D5000 + n, 0x4A00)        # same shape as real ids: 3 bytes, 0, 0, 1 byte, 0, 0


def _rec(op: int, sid: bytes, key: int, count: int, container: int = 1, slot: int = 7) -> bytes:
    return bytes([op, 0]) + sid + struct.pack("<IQBH", key, count, container, slot) + bytes(14)


def _msg(*records: bytes, n: int | None = None) -> bytes:
    return bytes([len(records) if n is None else n]) + b"".join(records) + b"\x00"


A, B = 610610015, 510716014


# --- real fixtures ---------------------------------------------------------------------------------

def test_parse_login_reads_every_container():
    stacks = inv.parse_login(_login(), KEYS)
    assert all(isinstance(sid, bytes) and len(sid) == 8 for sid in stacks)
    per_container = Counter(st.container for st in stacks.values())
    assert {str(c): n for c, n in per_container.items()} == MANIFEST["login"]["stacks_per_container"]
    for c in ("1", "15", "11"):
        assert inv.totals(stacks, int(c)) == MANIFEST["login"]["totals"][c]
    assert inv.totals(stacks) == MANIFEST["login"]["totals"]["1"]                # default is the bag


def test_parse_inventory_counts_only_the_bag_not_warehouse_or_equipped():
    bag = MANIFEST["login"]["totals"]["1"]
    assert inv.parse_inventory(_login(), KEYS) == bag
    # the warehouse holds more of some bag items; those must not be added in
    shared = set(bag) & set(MANIFEST["login"]["totals"]["15"])
    assert shared


CHANGE_FILES = [f["file"] for f in MANIFEST["changes"]] + [k + ".bin" for k in MANIFEST["conn38"]]


def _expected_records(name: str) -> list[list]:
    for f in MANIFEST["changes"]:
        if f["file"] == name:
            return f["records"]
    return MANIFEST["conn38"][name.removesuffix(".bin")]


@pytest.mark.parametrize("name", CHANGE_FILES)
def test_parse_changes_matches_decoded_fixture(name):
    assert _rows(inv.parse_changes(_bin(name))) == _expected_records(name)


def test_fixtures_include_the_long_change_lists():
    assert sorted(len(f["records"]) for f in MANIFEST["changes"])[-2:] == [14, 60]


def test_replaying_a_session_ends_at_the_next_login_totals():
    stacks = inv.parse_login(_login(), KEYS)
    changed = [inv.apply_changes(stacks, inv.parse_changes(_bin(f["file"])), KEYS) for f in MANIFEST["changes"]]
    for c in ("1", "15", "11"):
        assert inv.totals(stacks, int(c)) == MANIFEST["final_totals"][c]
    # container 18 removal, the bag re-sort and the Kinah updates (Kinah is never kept) leave the bag totals alone
    assert changed == MANIFEST["bag_changed_per_frame"] == [False, True, False, True, True, True, False, False]


# --- edge cases on hand-built messages -------------------------------------------------------------

def test_add_then_remove():
    stacks: dict = {}
    assert inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.ADD, _id(1), A, 5),
                                                            _rec(inv.ADD, _id(2), A, 3, slot=8))), {A})
    assert inv.totals(stacks) == {str(A): 8}
    assert stacks[_id(1)] == inv.Stack(str(A), 5, inv.CONTAINER_INVENTORY)
    assert inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.REMOVE, _id(1), A, 0))), {A})
    assert _id(1) not in stacks
    assert inv.totals(stacks) == {str(A): 3}
    assert inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.UPDATE, _id(2), A, 10, slot=8))), {A})
    assert inv.totals(stacks) == {str(A): 10}


def test_update_or_remove_of_an_unknown_id_is_ignored():
    stacks = {_id(1): inv.Stack(str(A), 5, 1)}
    before = dict(stacks)
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.UPDATE, _id(9), A, 7))), {A})
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.REMOVE, _id(9), A, 0))), {A})
    assert stacks == before


def test_temporary_container_is_skipped():
    stacks = {_id(1): inv.Stack(str(A), 5, 1)}
    before = dict(stacks)
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.ADD, _id(4), A, 1, container=4))), {A})
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.REMOVE, _id(4), A, 0, container=4))), {A})
    assert stacks == before and inv.totals(stacks) == {str(A): 5}


def test_unknown_item_key_is_skipped():
    stacks = {_id(1): inv.Stack(str(A), 5, 1)}
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.ADD, _id(2), B, 4))), {A})
    assert inv.totals(stacks) == {str(A): 5}


def test_warehouse_change_does_not_count_as_bag_change():
    stacks = {_id(1): inv.Stack(str(A), 5, 1), _id(2): inv.Stack(str(A), 9, 15)}
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.UPDATE, _id(2), A, 12, container=15))), {A})
    assert inv.totals(stacks, 15) == {str(A): 12} and inv.totals(stacks) == {str(A): 5}


def test_count_at_or_above_max_count_drops_the_stack():
    stacks = {_id(1): inv.Stack(str(A), 5, 1), _id(2): inv.Stack(str(B), 2, 1)}
    assert inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.UPDATE, _id(1), A, inv.MAX_COUNT))), {A, B})
    assert _id(1) not in stacks and inv.totals(stacks) == {str(B): 2}
    assert not inv.apply_changes(stacks, inv.parse_changes(_msg(_rec(inv.ADD, _id(3), A, 18_450_004))), {A, B})
    assert inv.totals(stacks) == {str(B): 2}


def test_login_leaves_out_kinah():
    stacks = inv.parse_login(_login(), KEYS)
    assert len(stacks) == MANIFEST["login"]["records"] - 1
    assert all(st.item_key != "930100031" for st in stacks.values())


def test_truncated_change_list_raises():
    with pytest.raises(ValueError):
        inv.parse_changes(_msg(_rec(inv.ADD, _id(1), A, 1), n=2))


# --- GameTracker and Store ---------------------------------------------------------------------------

def _inventory_ts(s: Store) -> set[float]:
    return {ts for (ts,) in s.db.execute("SELECT DISTINCT ts FROM inventory")}


def test_tracker_ignores_changes_until_a_login_is_seen():
    s = _store()
    game, conn = inv.GameTracker(s), inv.GameConnection()
    assert conn.stacks is None
    first = MANIFEST["changes"][-1]
    game.on_frame(conn, inv.CHANGE_OPCODE, _bin(first["file"]), first["t"])
    assert conn.stacks is None
    assert s.latest_inventory() == (None, {})


def test_tracker_keeps_the_bag_up_to_date_after_login():
    s = _store()
    login_t = MANIFEST["login"]["t"]
    s.set_inventory(login_t - 86400, {"510716014": 1})                 # an earlier session's snapshot
    game, conn = inv.GameTracker(s), inv.GameConnection()
    game.on_frame(conn, 0x5611, _login(), login_t)
    assert s.latest_inventory() == (login_t, MANIFEST["login"]["totals"]["1"])
    for f in MANIFEST["changes"]:
        game.on_frame(conn, inv.CHANGE_OPCODE, _bin(f["file"]), f["t"])
    last_t = MANIFEST["last_bag_change_t"]                   # the trailing Kinah-only frames store nothing
    assert s.latest_inventory() == (last_t, MANIFEST["final_totals"]["1"])
    assert _inventory_ts(s) == {login_t - 86400, last_t}           # the login snapshot was updated in place


def test_second_login_on_a_new_connection_starts_fresh():
    s = _store()
    game, old = inv.GameTracker(s), inv.GameConnection()
    game.on_frame(old, 0x5611, _login(), MANIFEST["login"]["t"])
    for f in MANIFEST["changes"]:
        game.on_frame(old, inv.CHANGE_OPCODE, _bin(f["file"]), f["t"])

    new = inv.GameConnection()
    c38 = {k: _bin(k + ".bin") for k in MANIFEST["conn38"]}
    game.on_frame(new, inv.CHANGE_OPCODE, c38["c38_561b_75_3"], NOW - 10)    # no login on this connection yet
    assert new.stacks is None and s.latest_inventory()[0] == MANIFEST["last_bag_change_t"]

    game.on_frame(new, 0x5611, _login(), NOW)
    assert new.stacks is not old.stacks
    assert s.latest_inventory() == (NOW, MANIFEST["login"]["totals"]["1"])
    game.on_frame(new, inv.CHANGE_OPCODE, c38["c38_561b_71_3"], NOW + 1)     # container 4 add ...
    game.on_frame(new, inv.CHANGE_OPCODE, c38["c38_561b_71_5"], NOW + 2)     # ... and remove: nothing stored
    game.on_frame(new, inv.CHANGE_OPCODE, c38["c38_561b_16_3"], NOW + 3)     # id from another session: ignored
    assert s.latest_inventory() == (NOW, MANIFEST["login"]["totals"]["1"])
    game.on_frame(new, inv.CHANGE_OPCODE, c38["c38_561b_75_3"], NOW + 4)     # new bag stack, key 610530014 x1
    expected = dict(MANIFEST["login"]["totals"]["1"])
    expected["610530014"] = expected.get("610530014", 0) + 1
    assert s.latest_inventory() == (NOW + 4, expected)


def test_update_inventory_inserts_into_an_empty_table():
    s = Store(":memory:")
    s.update_inventory(NOW, {"610610015": 2})
    assert s.latest_inventory() == (NOW, {"610610015": 2})


def test_update_inventory_replaces_only_the_newest_snapshot():
    s = Store(":memory:")
    s.set_inventory(NOW - 100, {"a": 1})
    s.set_inventory(NOW - 50, {"a": 2, "b": 1})
    s.update_inventory(NOW, {"a": 3})
    assert s.latest_inventory() == (NOW, {"a": 3})
    assert _inventory_ts(s) == {NOW - 100, NOW}
