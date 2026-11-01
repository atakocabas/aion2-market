import json
import urllib.parse
from datetime import datetime
from pathlib import Path

import pytest

from aion2market import dashboard, exchange, recipes, sync
from aion2market.store import Store


@pytest.fixture(autouse=True)
def no_recipe_keys(monkeypatch):
    """These tests count requests/rows for the items they create; crafting items are tested elsewhere."""
    monkeypatch.setattr(recipes, "all_keys", lambda: set())


HISTORY = json.loads((Path(__file__).parent / "fixtures" / "exchange_prices_30d.json").read_text())
HISTORY_END = datetime.fromisoformat("2026-10-29T17:28:01.976400+00:00").timestamp()


NAMES = json.loads((Path(__file__).parent / "fixtures" / "exchange_items_names.json").read_text())


def test_names_fill_only_what_nc_does_not_know():
    assert exchange.parse_names(NAMES) == [
        ("600590001", "Balaur's Essence", "Crafting Material"),        # category mapped to NC's label
        ("602460006", "Sealed Dark Veil Wings", "Sealed wings"),
        ("514310198", None, "Pantheon Decor")]                          # no name, but a category
    s = Store(":memory:")
    s.set_meta("exchange.server", "12306")
    s.add_snapshots(NOW - 60, 12306, [("600590001", 1.0, 1), ("602460006", 1.0, 1), ("514310198", 1.0, 1)])
    s.set_item_info("600590001", {"name": "NC Name", "categoryName": "NC Cat"}, 0)    # NC knows this one
    exchange.import_once(s, fetcher=lambda url: NAMES, now=NOW, delay=0)
    assert s.name("600590001") == "NC Name"
    assert s.name("602460006") == "Sealed Dark Veil Wings" and s.resolve("dark veil") == ["602460006"]
    info = s.item_info()
    assert info["602460006"]["source"] == "aion2.exchange" and info["602460006"]["category"] == "Sealed wings"
    assert s.name("514310198") is None and info["514310198"]["category"] == "Pantheon Decor"
    s.set_name("602460006", "Benim adım")
    assert s.name("602460006") == "Benim adım"
    # a later response without a name never erases the known one
    s.set_exchange_names([("602460006", None, None)], NOW + 1)
    s.clear_name("602460006")
    assert s.name("602460006") == "Sealed Dark Veil Wings"


def test_parse_history_reads_six_hour_buckets():
    rows = exchange.parse_history(HISTORY)
    assert len(rows) == 6
    ts, span, low, high, avg, close, listings, samples = rows[0]
    assert span == 6 * 3600 and (low, high, close, listings, samples) == (54000, 69860, 59000, 85, 23)
    assert exchange.parse_history({"bucket": "weird", "points": HISTORY["points"]}) == []


def test_backfill_loads_ranges_and_closing_prices_once():
    s = Store(":memory:")
    s.add_snapshots(HISTORY_END - 60, 12306, [("610610015", 56470.0, 66), ("610610014", 3000.0, 9)])
    urls = []

    def fake(url):
        urls.append(url)
        return HISTORY if "/610610015/" in url else {"bucket": "6h", "points": []}

    assert exchange.backfill(s, 12306, fetcher=fake, delay=0) == (2, 0, 0)
    assert urls[0].endswith("/items/610610014/prices?server=12306&range=30d")
    ranges = s.ranges("610610015", 12306)
    assert len(ranges) == 6 and ranges[-1][2:4] == (43300.0, 59000.0)
    closes = s.db.execute("SELECT ts, min_unit_price FROM price_snapshots WHERE origin = 'exchange' "
                          "AND item_key = '610610015' ORDER BY ts").fetchall()
    # the last bucket (12:00-18:00 while the range ends 17:28) is unfinished: range kept, no price point
    assert [p for _, p in closes] == [59000, 55555, 54999, 69999, 66650]
    assert closes[-1][0] < HISTORY_END
    # second run: both items were fetched once already (even the one without history), nothing is asked again
    urls.clear()
    assert exchange.backfill(s, 12306, fetcher=fake, delay=0) == (0, 2, 0) and urls == []
    # The week change now has a real base; the site's history starts on 6 Oct (~23.5 days),
    # so the month change uses that oldest point and stays marked as partial.
    row = {r["item_key"]: r for r in dashboard.item_rows(s, HISTORY_END, 12306)["items"]}["610610015"]
    assert row["week"]["price"] == 54999 and not row["week"]["partial"]
    assert row["month"]["price"] == 59000 and row["month"]["partial"]
    detail = dashboard.item_detail(s, "610610015", 12306)          # ranges of the last 31 days (wall clock)
    assert all(r[1] == 6 * 3600 and r[2] <= r[5] <= r[3] for r in detail["ranges"])

NOW = 1_800_000_000.0
ISO_NOW = "2027-01-15T08:00:00Z"            # == NOW


def _payload(*items):
    return {"items": [{"item_key": k, "price": p, "listings": n, "change_pct": -1.5, "captured_at": t}
                      for k, p, n, t in items]}


def test_import_stores_exchange_rows_in_batches_and_skips_bad_ones():
    s = Store(":memory:")
    s.add_snapshots(NOW - 3600, 12306, [(str(610610000 + i), 10.0, 1) for i in range(150)])
    s.set_meta("exchange.server", "12315")
    urls = []

    def fake(url):
        urls.append(url)
        keys = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["keys"][0].split(",")
        return _payload((int(keys[0]), 82000, 12, ISO_NOW),
                        (keys[1], 0, 3, ISO_NOW),                   # no price: skipped
                        (keys[2], 5, 1, None),                      # no time: skipped
                        ("junk", 5, 1, ISO_NOW))                    # bad key: skipped

    lines = exchange.import_once(s, fetcher=fake, now=NOW, delay=0)
    assert len(urls) == 2 and all("server=12315" in u and "limit=100" in u for u in urls)
    rows = s.db.execute("SELECT server_id, item_key, min_unit_price, sale_count, origin FROM price_snapshots "
                        "WHERE origin = 'exchange' ORDER BY item_key").fetchall()
    assert rows == [(12315, "610610000", 82000.0, 12, "exchange"), (12315, "610610100", 82000.0, 12, "exchange")]
    assert "2 yeni" in lines[0]
    assert exchange.import_once(s, fetcher=fake, now=NOW, delay=0) == []          # same snapshot: nothing new


def test_fresh_prices_on_own_server_alert():
    s = Store(":memory:")
    s.add_snapshots(NOW - 7200, 12306, [("610610015", 90000.0, 5)])
    s.watch("610610015", 85000, 0)
    s.set_meta("exchange.server", "12306")
    sent = []
    exchange.import_once(s, fetcher=lambda url: _payload((610610015, 82000, 9, ISO_NOW)),
                         notifier=lambda a: sent.append(a) or [], now=NOW, delay=0)
    assert [a.price for a in sent] == [82000.0]
    assert s.home_server() == 12306                                   # exchange rows never become "mine"


def test_exchange_rows_are_not_uploaded_to_the_shared_store():
    s = Store(":memory:")
    s.set_meta("exchange.server", "12315")
    s.add_snapshots(NOW, 12306, [("1", 5.0, 1)])
    exchange.import_once(s, fetcher=lambda url: _payload((2, 7, 1, ISO_NOW)), now=NOW, delay=0)
    sent = []

    class Cloud(sync.ShareClient):
        def request(self, method, path, body=None):
            sent.append(body)
            return {"rows": [], "next": 0, "more": False, "servers": []}
    sync.upload_pending(s, Cloud("https://x", "k"))
    assert [r[1] for b in sent if b for r in b.get("snapshots", [])] == ["1"]


def test_on_by_default_for_own_server_until_disabled():
    s = Store(":memory:")
    assert exchange.server_of(s) is None                              # game never opened the market: nothing to ask
    s.add_snapshots(NOW - 60, 12306, [("1", 5.0, 1)])
    urls = []

    def fake(url):
        urls.append(url)
        return _payload((1, 4, 2, ISO_NOW))
    exchange.import_once(s, fetcher=fake, now=NOW, delay=0)
    assert exchange.server_of(s) == 12306 and "server=12306" in urls[0]
    s.set_meta("exchange.server", "12315")                            # chosen with `setup`
    assert exchange.server_of(s) == 12315
    s.set_meta("exchange.enabled", "0")                               # what `exchange disable` writes
    urls.clear()
    assert exchange.server_of(s) is None and "kapalı" in exchange.import_once(s, fetcher=fake, now=NOW, delay=0)[0]
    assert urls == []


def test_errors_are_reported_not_raised():
    s = Store(":memory:")
    s.add_snapshots(NOW, 12306, [("1", 5.0, 1)])
    s.set_meta("exchange.server", "12306")

    def down(url):
        raise exchange.ExchangeError("HTTP 429")
    assert "429" in exchange.import_once(s, fetcher=down, now=NOW, delay=0)[0]
    assert s.get_meta("exchange.last_error") == "HTTP 429"
