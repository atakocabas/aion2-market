import json
import sqlite3

import pytest

from aion2market import dashboard, iteminfo
from aion2market.store import Store

ODYLE = {"id": 610610015, "name": "Pure Odyle", "grade": "Legend", "gradeName": "Epic",
         "categoryName": "Gatherable Material", "type": "Misc", "icon": "https://assets.example/od.png"}


def _store():
    s = Store(":memory:")
    s.add_snapshots(1000.0, 12306, [("610610015", 56470.0, 90), ("514310198", 1.0, 1), ("110230006", 5.0, 2)])
    return s


def test_fill_missing_stores_found_and_unknown_and_skips_them_next_time():
    s = _store()
    calls = []

    def fake(key):
        calls.append(key)
        if key == "110230006":
            raise OSError("timeout")
        return ODYLE if key == "610610015" else None

    assert iteminfo.fill_missing(s, delay=0, fetcher=fake) == (1, 1, 1)
    assert s.name("610610015") == "Pure Odyle"
    assert s.item_info()["610610015"]["grade_name"] == "Epic"
    calls.clear()
    iteminfo.fill_missing(s, delay=0, fetcher=fake)
    assert calls == ["110230006"]          # unknown keys wait a few hours; failed ones retry


def test_user_name_wins_over_official_and_both_resolve():
    s = _store()
    s.set_item_info("610610015", ODYLE, 0)
    assert s.resolve("pure") == ["610610015"]
    s.set_name("610610015", "Saf Odyle")
    assert s.name("610610015") == "Saf Odyle" and s.resolve("saf") == ["610610015"]
    assert s.resolve("pure") == []                                 # the user's name replaces it
    s.clear_name("610610015")
    assert s.name("610610015") == "Pure Odyle"


def test_dashboard_rows_carry_official_data():
    s = _store()
    s.set_item_info("610610015", ODYLE, 0)
    rows = {r["item_key"]: r for r in dashboard.item_rows(s, 2000.0)["items"]}
    r = rows["610610015"]
    assert (r["name"], r["custom_name"], r["icon"], r["category"]) == \
        ("Pure Odyle", False, "https://assets.example/od.png", "Gatherable Material")
    assert rows["514310198"]["name"] is None


def test_fetch_treats_id_zero_as_unknown(monkeypatch):
    class Resp:
        def __init__(self, body):
            self.body = body
        def read(self):
            return self.body
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    seen = []
    def fake_urlopen(req, timeout):
        seen.append(req.full_url)
        return Resp(json.dumps({"id": 0}).encode())
    monkeypatch.setattr(iteminfo.urllib.request, "urlopen", fake_urlopen)
    assert iteminfo.fetch("514310198") is None
    assert seen[0].startswith("https://tw.ncsoft.com/aion2/api/gameconst/item?id=514310198")


SWORD = {
    "id": 110230019, "name": "Star Dragon Lord Longsword", "grade": "Unique", "gradeName": "Unique",
    "icon": "https://assets.example/sword.png", "level": 70, "levelValue": 0, "enchantLevel": 0, "storable": True,
    "tradable": True, "tradablePersonal": True, "enchantable": True, "decomposable": True, "maxEnchantLevel": 15,
    "maxExceedEnchantLevel": 5, "raceName": "Asmodians", "classNames": ["Templar"], "categoryName": "Longsword",
    "type": "Equip", "equipLevel": 45, "magicStoneSlotCount": 4, "godStoneSlotCount": 1, "costumes": [{"id": 1}],
    "subStatCount": 5, "subSkillCountMax": 5, "subStatRandom": True,
    "mainStats": [{"id": "WeaponFixingDamage", "name": "Attack", "minValue": "284", "value": "355", "extra": "0",
                   "exceed": False},
                  {"id": "PvEAmplifyDamage", "name": "PvE Damage Boost", "value": "5%", "extra": "0%", "exceed": False}],
    "subStats": [{"id": "STR", "name": "Might", "minValue": "53", "value": "68"}],
    "sources": ["Crafting"], "favorite": False}
MANASTONE = {
    "id": 511360003, "name": "Intermediate Manastone", "desc": "Can be engraved on Manastone slots.\nThe type varies.",
    "grade": "Common", "gradeName": "Common", "icon": "https://assets.example/ms.png", "level": 0, "equipLevel": 1,
    "raceName": "All", "categoryName": "Manastone", "type": "Usable", "tradable": True, "storable": True,
    "enchantable": False, "subStatCount": 0, "sources": ["Hidden Cube", "Crafting", "Supply Request"]}


@pytest.fixture(autouse=True)
def _no_remembered_failures():
    iteminfo._tooltip_failed.clear()


def _never(key):
    raise AssertionError(f"unexpected lookup of {key}")


def test_old_database_gets_the_detail_column(tmp_path):
    path = tmp_path / "market.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE item_info (item_key TEXT PRIMARY KEY, found INTEGER NOT NULL, name TEXT, grade TEXT, "
                "grade_name TEXT, category TEXT, type TEXT, icon TEXT, fetched_ts REAL NOT NULL)")
    old.execute("INSERT INTO item_info VALUES ('610610015', 1, 'Pure Odyle', 'Legend', 'Epic', 'Material', 'Misc', "
                "'od.png', 5.0)")
    old.commit()
    old.close()
    s = Store(path)
    assert s.item_info_for("610610015") == {
        "name": "Pure Odyle", "grade": "Legend", "grade_name": "Epic", "category": "Material", "type": "Misc",
        "icon": "od.png", "source": "nc", "detail": None}
    s.set_item_info("110230019", SWORD, 6.0)                       # old and new rows live side by side
    assert s.item_info_for("110230019")["detail"]["item_level"] == 70
    assert s.item_info()["610610015"]["name"] == "Pure Odyle"
    s.close()


def test_set_item_info_stores_a_compact_detail():
    s = _store()
    s.set_item_info("110230019", SWORD, 0)
    s.set_item_info("514310198", None, 0)
    detail = s.item_info_for("110230019")["detail"]
    assert detail["main_stats"][0] == {"name": "Attack", "value": "355", "min": "284"}
    assert "costumes" not in detail and "icon" not in detail       # only what the tooltip shows
    assert s.item_info_for("514310198") is None
    assert s.db.execute("SELECT detail FROM item_info WHERE item_key = '514310198'").fetchone() == (None,)


def test_fill_missing_stores_the_detail_of_new_items():
    s = _store()
    iteminfo.fill_missing(s, delay=0, fetcher=lambda key: MANASTONE if key == "514310198" else None)
    assert s.item_info_for("514310198")["detail"]["sources"] == ["Hidden Cube", "Crafting", "Supply Request"]


def test_tooltip_of_equipment():
    s = _store()
    s.set_item_info("110230019", SWORD, 0)
    s.set_name("110230019", "Kılıcım")
    assert iteminfo.tooltip(s, "110230019", fetcher=_never) == {
        "item_key": "110230019", "name": "Kılıcım", "official_name": "Star Dragon Lord Longsword",
        "grade_name": "Unique", "category": "Longsword", "type": "Equip", "icon": "https://assets.example/sword.png",
        "detail": True, "item_level": 70, "equip_level": 45, "race": "Asmodians", "classes": ["Templar"],
        "desc": None, "tradable": True, "enchantable": True, "max_enchant": 15, "max_exceed": 5,
        "manastone_slots": 4, "godstone_slots": 1,
        "main_stats": [{"name": "Attack", "value": "355", "min": "284"},
                       {"name": "PvE Damage Boost", "value": "5%", "min": None}],
        "sub_stats": [{"name": "Might", "value": "68", "min": "53"}], "sub_stat_count": 5, "sources": ["Crafting"]}


def test_tooltip_of_a_consumable_has_no_equipment_fields():
    s = _store()
    s.set_item_info("511360003", MANASTONE, 0)
    t = iteminfo.tooltip(s, "511360003", fetcher=_never)
    assert t["detail"] and t["name"] == t["official_name"] == "Intermediate Manastone"
    assert t["desc"].startswith("Can be engraved") and t["sources"][0] == "Hidden Cube"
    assert (t["item_level"], t["equip_level"], t["race"], t["classes"]) == (None, None, None, [])
    assert (t["tradable"], t["enchantable"], t["max_enchant"], t["max_exceed"]) == (True, False, None, None)
    assert (t["manastone_slots"], t["godstone_slots"], t["sub_stat_count"]) == (None, None, None)
    assert t["main_stats"] == [] and t["sub_stats"] == []


def test_tooltip_fetches_a_known_item_once_and_keeps_its_row():
    s = _store()
    s.set_item_info("610610015", ODYLE, 0)
    s.db.execute("UPDATE item_info SET detail = NULL")             # as stored before details were kept
    rowid = s.db.execute("SELECT rowid FROM item_info").fetchone()[0]
    calls = []

    def fake(key):
        calls.append(key)
        return dict(ODYLE, name="Renamed", level=3, tradable=True)

    t = iteminfo.tooltip(s, "610610015", fetcher=fake)
    assert t["detail"] and t["item_level"] == 3 and t["tradable"] is True
    assert t["official_name"] == "Pure Odyle"                      # only the detail is added to a known item
    assert iteminfo.tooltip(s, "610610015", fetcher=fake) == t and calls == ["610610015"]
    assert s.db.execute("SELECT rowid FROM item_info").fetchone()[0] == rowid      # sync won't upload it again


def test_tooltip_looks_up_an_item_never_seen_before():
    s = _store()
    t = iteminfo.tooltip(s, "511360003", fetcher=lambda key: MANASTONE, now=50.0)
    assert t["detail"] and t["name"] == "Intermediate Manastone" and t["category"] == "Manastone"
    assert s.item_info()["511360003"]["icon"] == MANASTONE["icon"]


def test_failed_tooltip_lookup_keeps_the_name_and_waits_before_retrying():
    s = _store()
    s.set_item_info("610610015", ODYLE, 0)
    s.db.execute("UPDATE item_info SET detail = NULL")
    calls = []

    def failing(key):
        calls.append(key)
        raise OSError("timeout")

    def unknown(key):
        calls.append(key)
        return None

    t = iteminfo.tooltip(s, "610610015", fetcher=failing, now=1000.0)
    assert t["detail"] is False and t["name"] == "Pure Odyle" and t["grade_name"] == "Epic"
    assert t["item_level"] is None and t["main_stats"] == [] and t["sources"] == []
    assert iteminfo.tooltip(s, "610610015", fetcher=failing, now=1300.0) == t and len(calls) == 1
    iteminfo.tooltip(s, "610610015", fetcher=unknown, now=1000.0 + iteminfo.TOOLTIP_RETRY_AFTER)
    assert len(calls) == 2
    assert s.name("610610015") == "Pure Odyle" and s.item_info()["610610015"]["icon"] == ODYLE["icon"]
    # an item nobody knows: every key is still there
    t = iteminfo.tooltip(s, "999", fetcher=unknown, now=1000.0)
    assert t["detail"] is False and t["name"] is None and t["official_name"] is None and t["classes"] == []
    assert s.db.execute("SELECT COUNT(*) FROM item_info").fetchone()[0] == 1


def test_fetch_passes_its_timeout(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        seen.append(timeout)
        raise OSError("down")
    monkeypatch.setattr(iteminfo.urllib.request, "urlopen", fake_urlopen)
    s = _store()
    assert iteminfo.tooltip(s, "610610015")["detail"] is False     # the real fetch, with the short timeout
    assert seen == [iteminfo.TOOLTIP_TIMEOUT]
