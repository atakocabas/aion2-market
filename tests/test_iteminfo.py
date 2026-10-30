import json

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
    assert calls == ["110230006"]          # unknown keys wait a week; failed ones retry


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
