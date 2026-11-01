import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from aion2market import dashboard, updates
from aion2market.store import Store

DAY = 86400
NOW = 1_800_000_000.0


def _store():
    s = Store(":memory:")
    s.set_name("1", "Pure Odyle")
    # item 1: 40 days of history; item 2 only appears today
    s.add_snapshots(NOW - 40 * DAY, 12306, [("1", 100.0, 5)])
    s.add_snapshots(NOW - 8 * DAY, 12306, [("1", 90.0, 5)])
    s.add_snapshots(NOW - 2 * DAY, 12306, [("1", 80.0, 6)])
    s.add_snapshots(NOW - 3600, 12306, [("1", 75.0, 7), ("2", 50.0, 1)])
    s.add_snapshots(NOW - 60, 12306, [("1", 60.0, 8), ("2", 55.0, 2)])
    s.add_snapshots(NOW - 55, 12306, [("1", 60.0, 8)])   # same market opening, seconds later
    return s


def test_changes_per_period():
    rows = {r["item_key"]: r for r in dashboard.item_rows(_store(), NOW)["items"]}
    one = rows["1"]
    assert one["price"] == 60 and one["name"] == "Pure Odyle" and one["listed"]
    assert one["prev"]["price"] == 75 and one["prev"]["change"] == -20.0      # skips the 5 s apart duplicate
    assert one["week"]["price"] == 90 and one["week"]["change"] == -33.33 and not one["week"]["partial"]
    assert one["month"]["price"] == 100 and one["month"]["change"] == -40.0


def test_short_history_is_partial_and_new_items_have_no_base():
    rows = {r["item_key"]: r for r in dashboard.item_rows(_store(), NOW)["items"]}
    two = rows["2"]
    assert two["prev"]["change"] == 10.0
    assert two["week"]["partial"] and two["week"]["price"] == 50      # oldest point stands in for 7 days ago
    s = Store(":memory:")
    s.add_snapshots(NOW, 1, [("3", 10.0, 1)])
    (only,) = dashboard.item_rows(s, NOW)["items"]
    assert only["prev"]["change"] is None and only["week"]["change"] is None


def test_item_missing_from_latest_listing_is_not_listed():
    s = _store()
    s.add_snapshots(NOW - 10, 12306, [("1", 60.0, 8)])
    s.add_snapshots(NOW - 30 * 60 + 0.5, 12306, [("4", 5.0, 1)])
    rows = {r["item_key"]: r for r in dashboard.item_rows(s, NOW)["items"]}
    assert rows["1"]["listed"] and not rows["4"]["listed"]
    assert rows["4"]["count"] == 0 and rows["4"]["last_count"] == 1 and rows["1"]["count"] == 8


def test_small_update_after_a_scan_does_not_unlist_the_scan():
    s = Store(":memory:")
    s.add_snapshots(NOW - 3600, 12306, [(str(k), 10.0, 3) for k in range(10)])     # full market scan
    s.add_snapshots(NOW - 1800, 12306, [("0", 9.0, 4), ("10", 5.0, 2)])            # an item search, shared data
    rows = {r["item_key"]: r for r in dashboard.item_rows(s, NOW)["items"]}
    assert all(r["listed"] for r in rows.values())
    assert rows["5"]["count"] == 3 and rows["0"]["count"] == 4
    s.add_snapshots(NOW - 60, 12306, [(str(k), 10.0, 3) for k in range(1, 10)])    # a newer scan without 0 and 10
    rows = {r["item_key"]: r for r in dashboard.item_rows(s, NOW)["items"]}
    assert not rows["0"]["listed"] and not rows["10"]["listed"] and rows["5"]["listed"]


def _series(store, key, points):
    for ts, price in points:
        store.add_snapshots(ts, 12306, [(key, price, 3)])


def test_bogus_listings_are_not_used_as_change_bases():
    s = Store(":memory:")
    # Normal ~100; a lone 10M placeholder sat on the market exactly 7 days ago.
    _series(s, "1", [(NOW - 20 * DAY, 100.0), (NOW - 7 * DAY - 10, 10_000_000.0), (NOW - 6 * DAY, 105.0),
                     (NOW - 2 * DAY, 98.0), (NOW - 3600, 10_000_000.0), (NOW - 60, 90.0)])
    r = {x["item_key"]: x for x in dashboard.item_rows(s, NOW)["items"]}["1"]
    assert r["suspect"] is None and r["median30"] == 102.5          # median of 90, 98, 100, 105, 10M, 10M
    assert r["typical"] == 97.67                                    # 7-day mean of 105, 98, 90; 10M left out
    assert r["week"]["price"] == 100 and r["week"]["change"] == -10.0      # not -99.99 % from the 10M point
    assert r["prev"]["price"] == 98.0                                       # skips the 10M an hour ago
    assert all(p[1] < 1000 for p in r["spark"])


def test_current_outlier_is_flagged():
    s = Store(":memory:")
    _series(s, "hi", [(NOW - d * DAY, 100.0) for d in (6, 5, 4, 3)] + [(NOW - 60, 9_999_999.0)])
    _series(s, "lo", [(NOW - d * DAY, 100.0) for d in (6, 5, 4, 3)] + [(NOW - 60, 1.0)])
    _series(s, "few", [(NOW - 2 * DAY, 100.0), (NOW - 60, 9_999_999.0)])      # too little data: untouched
    rows = {x["item_key"]: x for x in dashboard.item_rows(s, NOW)["items"]}
    assert rows["hi"]["suspect"] == "high" and rows["hi"]["week"]["change"] is None
    assert rows["lo"]["suspect"] == "low" and rows["lo"]["week"]["change"] == -99.0
    assert rows["few"]["suspect"] is None and rows["few"]["prev"]["change"] > 1000


def test_deals_pick_recent_drops_below_normal_and_explain_why():
    s = Store(":memory:")
    days = (20, 15, 10, 8, 6, 4, 2)
    _series(s, "dip", [(NOW - d * DAY, 100.0) for d in days] + [(NOW - 60, 60.0)])         # sudden 40 % dip
    _series(s, "slide", [(NOW - d * DAY, p) for d, p in zip(days, (100, 100, 100, 100, 70, 65, 62), strict=True)]
            + [(NOW - 60, 50.0)])                                                            # week-long slide
    _series(s, "flat", [(NOW - d * DAY, 100.0) for d in days] + [(NOW - 60, 99.0)])         # no real discount
    _series(s, "new", [(NOW - 2 * DAY, 100.0), (NOW - DAY, 100.0), (NOW - 3600, 100.0),
                       (NOW - 1800, 100.0), (NOW - 60, 50.0)])                              # < 3 days of history
    for key in ("dip", "slide", "flat", "new"):
        s.db.execute("UPDATE price_snapshots SET sale_count = 12 WHERE item_key = ?", (key,))
    rows = dashboard.item_rows(s, NOW)["items"]
    picked = {r["item_key"]: r["deal"] for r in dashboard.deals(rows)}
    assert set(picked) == {"dip", "slide"}
    # 7-day average of 100, 100, 100 and the current 60 is 90
    assert picked["dip"]["discount"] == 33.3 and picked["dip"]["saving"] == 30
    assert "7 gün ortalamasının %33 altında" in picked["dip"]["reasons"] and "12 ilan" in picked["dip"]["reasons"]
    assert not picked["dip"]["sliding"] and picked["slide"]["sliding"]
    assert "düşüşte" in picked["slide"]["warning"]
    # the one-line note skips what the table's columns already show (discount, listings)
    assert [n["text"] for n in picked["dip"]["note"]] == ["son listelemede %40 düştü", "30 günün dibinde"]
    assert {"text": "haftadır düşüyor", "warn": True} in picked["slide"]["note"]
    assert [r["item_key"] for r in dashboard.deals(rows)][0] == "dip"


def test_deal_flip_profit_counts_the_market_fee():
    s = Store(":memory:")
    days = (20, 15, 10, 8, 6, 4, 2)
    _series(s, "dip", [(NOW - d * DAY, 100.0) for d in days] + [(NOW - 60, 60.0)])
    s.db.execute("UPDATE price_snapshots SET sale_count = 12")
    (d,) = [r["deal"] for r in dashboard.deals(dashboard.item_rows(s, NOW)["items"], fee_pct=12)]
    assert d["net_profit"] == 19 and d["profit_pct"] == 32.0               # 90 * 0.88 - 60
    assert any("+19" in reason for reason in d["reasons"])


def test_morph_table_compares_odyle_with_its_materials():
    rows = [{"item_key": k, "name": n, "price": p, "count": 5, "icon": None, "grade_name": None}
            for k, n, p in (("610610014", "Fine Odyle", 2000.0), ("610660030", "Fine Ruby Gemstone", 4000.0),
                            ("610620014", "Fine Orichalcum Ore", 1500.0))]
    table = {m["material"]["item_key"]: m for m in dashboard.morph_table(rows, 12)}
    ruby, ore = table["610660030"], table["610620014"]
    assert (ruby["craft_saving"], ruby["sell_profit"], ruby["sell_profit_pct"]) == (2000, 1520, 76.0)
    assert ore["craft_saving"] == -500 and ore["sell_profit"] < 0
    assert list(table) == ["610660030", "610620014"]                      # best first


def test_weekday_pattern_finds_the_cheap_day():
    import time as _t
    base = NOW - 28 * DAY
    series = {}
    for item in range(3):
        pts = []
        for h in range(0, 28 * 24, 3):
            ts = base + h * 3600
            pts.append((ts, 90.0 if _t.localtime(ts).tm_wday == 2 else 100.0, 1))   # Wednesdays 10 % cheaper
        series[str(item)] = pts
    summary = dashboard.pattern_summary(dashboard.weekday_pattern(series, NOW))
    assert summary["cheapest"] == "Çarşamba" and 9 < summary["spread"] < 12


def test_policies_set_the_market_fee():
    from aion2market.http1 import HttpMessage
    from aion2market.market import handle_exchange, sell_fee_pct
    s = Store(":memory:")
    assert sell_fee_pct(s) == 12.0
    req = HttpMessage("GET /trade/v1.0/policies?game_server_id=12306 HTTP/1.1", {}, b"")
    resp = HttpMessage("HTTP/1.1 200 OK", {}, json.dumps(
        {"fee": [{"fee_type": "1", "fee_rate": "10"}, {"fee_type": "3", "fee_rate": "5"}]}).encode())
    assert handle_exchange(s, req, resp) == ["Market kesintisi güncellendi: %15"]
    assert sell_fee_pct(s) == 15.0 and handle_exchange(s, req, resp) == []


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "status", lambda: {"available": False})   # no GitHub call from tests
    path = tmp_path / "m.db"
    monkeypatch.setenv("AION2_DB", str(path))
    _store_file = Store(path)
    _store_file.add_snapshots(NOW, 12306, [("1", 60.0, 8)])
    _store_file.close()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), dashboard.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_address[1], path
    httpd.shutdown()


def _req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
    r = c.getresponse()
    return r.status, r.read()


def test_http_api(server):
    port, path = server
    status, html = _req(port, "GET", "/")
    assert status == 200 and b"Fiyat de" in html
    status, body = _req(port, "GET", "/api/items")
    assert status == 200 and json.loads(body)["items"][0]["item_key"] == "1"
    status, _ = _req(port, "POST", "/api/name", {"item_key": "1", "name": "Pure Odyle"},
                     {"Content-Type": "application/json"})
    assert status == 200
    status, _ = _req(port, "POST", "/api/watch", {"item_key": "1", "target": "55000"},
                     {"Content-Type": "application/json"})
    detail = json.loads(_req(port, "GET", "/api/item/1")[1])
    assert detail["name"] == "Pure Odyle" and detail["watch"] == {"target": 55000}


def test_static_assets_are_served_from_an_allowlist(server):
    port, _ = server
    _, html = _req(port, "GET", "/")
    assets = {"app.css": "text/css", "i18n.js": "text/javascript", "core.js": "text/javascript",
              "pages.js": "text/javascript", "views.js": "text/javascript", "detail.js": "text/javascript",
              "main.js": "text/javascript"}
    for name, ctype in assets.items():
        assert f'"{name}?v={dashboard.__version__}"'.encode() in html
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", f"/{name}?v=1")
        r = c.getresponse()
        assert r.status == 200 and r.getheader("Content-Type") == ctype + "; charset=utf-8"
        assert r.getheader("Cache-Control") == "no-store" and r.read()
    for bad in ("/../store.py", "/%2e%2e/store.py", "/..%2fstore.py", "/web/app.css", "/icon.ico", "/x.js"):
        assert _req(port, "GET", bad)[0] in (403, 404)
    assert _req(port, "GET", "/app.css", headers={"Host": "evil.example:8765"})[0] == 403


def test_hide_settings_are_validated_and_persisted(server):
    port, path = server
    j = {"Content-Type": "application/json"}
    assert json.loads(_req(port, "GET", "/api/settings")[1])["exclude"] == {"rules": [], "items": [], "show_hidden": False}
    sent = {"exclude": {"rules": [{"grades": ["Rare"], "categories": ["Top", "Legs"]},
                                  {"grades": [], "categories": []},              # matches everything: dropped
                                  "junk"],
                        "items": ["610610015", "<script>"], "show_hidden": 1}}
    status, body = _req(port, "POST", "/api/settings", sent, j)
    expected = {"rules": [{"grades": ["Rare"], "categories": ["Top", "Legs"]}], "items": ["610610015"],
                "show_hidden": True}
    assert status == 200 and json.loads(body)["exclude"] == expected
    # stored in the database, so a new server (or another browser) gets the same settings
    assert dashboard.get_exclude(Store(path)) == expected


def test_cross_site_and_foreign_host_requests_are_refused(server):
    port, _ = server
    # form posts (no JSON content type) and DNS-rebinding hosts are rejected
    assert _req(port, "POST", "/api/name", {"item_key": "1", "name": "x"}, {"Content-Type": "text/plain"})[0] == 403
    assert _req(port, "GET", "/api/items", headers={"Host": "evil.example:8765"})[0] == 403


@pytest.mark.parametrize("installed", [True, False])
def test_npcap_status(monkeypatch, installed):
    from aion2market import app
    monkeypatch.setattr(app, "npcap_installed", lambda: installed)
    assert dashboard.npcap_status() == {"installed": installed, "url": app.NPCAP_URL}


def test_sync_switch_endpoint(server):
    port, path = server
    h = {"Content-Type": "application/json"}
    status, body = _req(port, "POST", "/api/sync", {"enabled": False}, h)
    assert status == 200 and json.loads(body)["enabled"] is False
    assert _req(port, "POST", "/api/sync", {"enabled": "yes"}, h)[0] == 400
    s = Store(path)
    assert s.get_meta("sync.enabled") == "0"
    s.close()
