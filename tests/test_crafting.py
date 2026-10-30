import pytest

from aion2market import crafting, exchange, recipes
from aion2market.store import Store

GUARD = recipes.CHAINS[0]


def _prices(**overrides):
    """Every Guard material at 10, outputs unlisted unless overridden."""
    prices = {key: {"price": 10.0, "count": 5} for step in GUARD["steps"] for key, _, _ in step["materials"]}
    prices.update({k: {"price": v, "count": 3} for k, v in overrides.items()})
    return prices


def _guard(prices, fee=12.0):
    return next(c for c in crafting.plan(prices, fee) if c["slot"] == "Guard")


def test_craft_costs_accumulate_with_expected_tries():
    g = _guard(_prices())
    s1, s2 = g["steps"][0]["result"], g["steps"][1]["result"]
    assert s1["attempt_cost"] == 100 and s1["craft_cost"] == round(100 * 4.295471)        # 10 units x 10
    assert s2["craft_cost"] == round(100 * 4.295471 + 140 * 4.226813)                      # 14 units in step 2
    assert s1["best"] == "craft" and s1["market_price"] is None
    assert g["route"] == "Baştan üret (1-4. adımlar)"


def test_buying_a_cheap_tier_cuts_the_route_and_profit_counts_the_fee():
    artisan = "115030014"
    g = _guard(_prices(**{artisan: 1000.0, "115030021": 1_000_000.0}))
    s3, s4 = g["steps"][2]["result"], g["steps"][3]["result"]
    assert s3["best"] == "buy" and s3["cost"] == 1000
    assert s4["best"] == "craft" and s4["craft_cost"] == round(1000 + 500 * 4.226543)      # 50 units in step 4
    assert s4["sell_profit"] == round(1_000_000 * 0.88 - s4["craft_cost"])
    assert g["route"] == "Artisan's Splendent Orichalcum Guard al, 4. adımı üret"
    normal = g["steps"][3]["normal_result"]
    assert normal["craft_cost"] == round(1000 + 500 * 1.056636)


def test_odyle_morph_used_when_cheaper_and_missing_prices_block_crafting():
    prices = _prices()
    prices["610620015"] = {"price": 50.0, "count": 5}           # Pure Orichalcum Ore, expensive
    prices["610610015"] = {"price": 10.0, "count": 5}           # Pure Odyle, cheap
    step3 = _guard(prices)["steps"][2]
    ore = next(m for m in step3["materials"] if m["item_key"] == "610620015")
    assert (ore["price"], ore["via"]) == (10.0, "odyle")
    del prices["610710001"]                                     # Orichalcum Ingot unpriced
    g = _guard(prices)
    assert g["steps"][0]["result"]["craft_cost"] is None and g["route"] == "Fiyat eksik"


def test_recipe_items_are_always_polled():
    s = Store(":memory:")
    assert recipes.all_keys() <= set(exchange.tracked_keys(s))
    assert len(recipes.all_keys()) == 62
