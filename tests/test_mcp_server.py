import asyncio
import json

import pytest
from mcp import Client

from aion2market import mcp_server as m
from aion2market.store import Store

T0 = 1_800_000_000.0


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "market.db"
    monkeypatch.setenv("AION2_DB", str(path))
    s = Store(path)
    s.set_name("610610015", "Pure Odyle")
    s.set_name("610610014", "Fine Odyle")
    s.add_snapshots(T0, 12306, [("610610015", 56500.0, 80), ("610610014", 9000.0, 12)])
    s.add_snapshots(T0 + 3600, 12306, [("610610015", 56470.0, 90)])
    sale = lambda sid, q, total: {"sale_id": sid, "game_item_key": "610610015", "game_item_quantity": str(q),
                                  "sale_price": str(total), "unit_price": f"{total / q:.4f}"}
    s.add_listings(T0 + 3600, 12306, [sale("a", 1, 81900), sale("b", 3, 169410), sale("c", 1, 82000)])
    s.close()
    return path


def test_get_price_by_partial_name(db):
    p = m.get_price("pure")
    assert p["item_key"] == "610610015"
    assert p["summary"]["min_unit_price"] == 56470
    assert p["last_search"]["cheapest_single_unit"] == 81900
    assert p["last_search"]["cheapest_unit_price"] == 56470


def test_ambiguous_and_unknown_names(db):
    assert "matches" in m.get_price("odyle")
    assert "known_items" in m.get_price("kinah")
    assert m.get_price("610610014")["summary"]["min_unit_price"] == 9000


def test_history_and_cheapest(db):
    h = m.price_history("Pure Odyle", days=100000)
    assert [x["min_unit_price"] for x in h["summary"]] == [56500, 56470]
    assert h["searches"][0]["cheapest_single_unit"] == 81900
    singles = m.cheapest_listings("Pure Odyle", quantity=1)["listings"]
    assert [x["total_price"] for x in singles] == [81900, 82000]


def test_watchlist(db):
    m.watch_item("Pure Odyle", target_price=60000)
    m.watch_item("Fine Odyle")
    items = m.list_watchlist()["items"]
    assert [(i["name"], i["at_or_below_target"]) for i in items] == [("Pure Odyle", True), ("Fine Odyle", None)]
    assert m.unwatch_item("Fine Odyle")["removed"] is True
    assert len(m.list_watchlist()["items"]) == 1


def test_name_item_and_recent_searches(db):
    assert "error" in m.name_item("abc", "x")
    assert m.recent_searches()["items"][0]["name"] == "Pure Odyle"
    m.name_item("610610015", "Saf Odyle")
    assert m.get_price("saf")["item_key"] == "610610015"


def test_over_mcp_protocol(db):
    async def run():
        async with Client(m.server) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            res = await client.call_tool("get_price", {"item": "Pure Odyle"})
            return names, res

    names, res = asyncio.run(run())
    assert {"get_price", "price_history", "watch_item", "unwatch_item", "list_watchlist",
            "cheapest_listings"} <= names
    data = res.structured_content or json.loads(res.content[0].text)
    assert data["last_search"]["cheapest_single_unit"] == 81900
