import pytest

from aion2market import crafting, exchange, recipes
from aion2market.store import Store

GUARD = next(c for c in recipes.CHAINS if c["slot"] == "Guard" and c["race"] == "Asmodians")


def _prices(**overrides):
    """Every Guard material at 10, outputs unlisted unless overridden."""
    prices = {key: {"price": 10.0, "count": 5} for step in GUARD["steps"] for key, _, _ in step["materials"]}
    prices.update({k: {"price": v, "count": 3} for k, v in overrides.items()})
    return prices


def _guard(prices, fee=12.0):
    return next(c for c in crafting.plan(prices, fee, race="Asmodians") if c["slot"] == "Guard")


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
    assert all(not recipes.is_npc_item(name) for name in _names(recipes.all_keys()))


def _names(keys):
    names = {}
    for r in recipes.RECIPES:
        names[r["key"]] = r["name"]
        names.update({k: n for k, n, _ in r["materials"]})
    return [names.get(k, "") for k in keys]


def test_chains_are_built_from_recipe_data():
    """The Asmodian Guard chain the app started with, now generated from the recipe data."""
    steps = GUARD["steps"]
    assert [s["output"][0] for s in steps] == ["115050016", "115040014", "115030014", "115030021"]
    assert steps[3]["normal_output"][0] == "115030019"
    assert sorted((k, q) for k, _, q in steps[0]["materials"]) ==         [("610530001", 5), ("610610013", 2), ("610710001", 3)]
    assert {(c["slot"], c["race"]) for c in recipes.CHAINS} >= {("Longsword", "Asmodians"), ("Greatsword", "Elyos")}


def test_single_recipe_profit_uses_cheapest_materials_and_marks_npc_items():
    ingot = next(r for r in recipes.SINGLES if r["key"] == "610710001" and r["qty"] == 1)
    ore, solvent = ingot["materials"][0][0], ingot["materials"][1]
    prices = {ore: {"price": 100.0, "count": 9}, "610710001": {"price": 500.0, "count": 9}}
    row = next(r for r in crafting.singles(prices, 10.0) if r["item_key"] == "610710001" and r["qty"] == 1)
    assert row["cost"] == 200 and row["npc"] and solvent[1].endswith("(Bound)")
    assert row["profit"] == round(500 * 0.9 - 200)
    # A chain material that is cheaper to craft than to buy uses the recipe
    mc = crafting.material_cost("610710001", prices)
    assert (mc["price"], mc["via"]) == (200.0, "craft_npc")


MATERIAL_KEYS = {"item_key", "name", "qty", "price", "via", "has_recipe"}


def test_recipes_of_a_single_recipe():
    ingot = next(r for r in recipes.SINGLES if r["key"] == "610710001" and r["qty"] == 1)
    ore = ingot["materials"][0][0]
    prices = {ore: {"price": 100.0, "count": 9}, "610710001": {"price": 500.0, "count": 9}}
    assert len(crafting.recipes_of("610710001", prices, 10.0)) == len(recipes.recipes_for("610710001"))
    found = crafting.recipes_of("610710001", prices, 10.0, race="Asmodians")
    assert [(r["race"], r["qty"]) for r in found] == [("Asmodians", 1), ("Asmodians", 10)]   # one per batch size
    r = found[0]
    assert (r["profession"], r["category"], r["mastery"], r["combo"], r["tries"]) == \
        (ingot["profession"], ingot["category"], 1, False, None)
    assert (r["cost"], r["unit_cost"], r["market_price"], r["npc"]) == (200, 200, 500.0, True)
    assert [set(m) for m in r["materials"]] == [MATERIAL_KEYS] * len(ingot["materials"])
    assert [(m["item_key"], m["price"], m["via"]) for m in r["materials"]][0] == (ore, 100.0, "market")
    assert r["materials"][1]["via"] == "npc"
    assert (found[1]["cost"], found[1]["unit_cost"]) == (2000, 200)


def test_recipes_of_a_chain_combo_tier_include_the_previous_tier():
    step2 = GUARD["steps"][1]
    [r] = crafting.recipes_of(step2["output"][0], _prices(), race="Asmodians")
    assert (r["profession"], r["category"], r["race"], r["qty"]) == (GUARD["profession"], "Guard", "Asmodians", 1)
    assert r["combo"] and r["tries"] == 4.226813 and r["mastery"] == step2["mastery"]
    first, *rest = r["materials"]
    assert (first["item_key"], first["qty"], first["via"], first["has_recipe"]) == ("115050016", 1, "craft", True)
    assert first["price"] == pytest.approx(100 * 4.295471)                  # crafting the tier before it
    assert [m["item_key"] for m in rest] == [k for k, _, _ in step2["materials"]]
    assert not any(m["has_recipe"] for m in rest) and all(set(m) == MATERIAL_KEYS for m in r["materials"])
    assert r["cost"] == 140 and r["unit_cost"] == round(100 * 4.295471 + 140 * 4.226813)   # as plan() has it
    assert r["market_price"] is None
    # the first tier consumes no equipment
    [r1] = crafting.recipes_of(GUARD["steps"][0]["output"][0], _prices())
    assert len(r1["materials"]) == len(GUARD["steps"][0]["materials"]) and r1["unit_cost"] == round(100 * 4.295471)
    assert [m["has_recipe"] for m in r1["materials"]] == [True, False, False]          # the ingot is crafted too


def test_recipes_of_the_normal_last_tier():
    prices = _prices(**{"115030014": 1000.0, "115030019": 9000.0})
    [r] = crafting.recipes_of("115030019", prices)
    assert not r["combo"] and r["tries"] == 1.056636 and r["market_price"] == 9000.0
    assert (r["materials"][0]["item_key"], r["materials"][0]["price"], r["materials"][0]["via"]) == \
        ("115030014", 1000.0, "market")                                      # buying the tier before is cheaper
    assert r["cost"] == 500 and r["unit_cost"] == round(1000 + 500 * 1.056636)
    [combo] = crafting.recipes_of("115030021", prices)
    assert combo["combo"] and combo["unit_cost"] == round(1000 + 500 * 4.226543)
    del prices["610710001"]                                                  # a material without a price
    [r] = crafting.recipes_of(GUARD["steps"][0]["output"][0], prices)
    assert r["cost"] is None and r["unit_cost"] is None


def test_recipes_of_follow_the_race_and_unknown_items_have_none():
    assert crafting.recipes_of("1", _prices()) == [] and not crafting.has_recipe("1")
    assert crafting.has_recipe("115030019") and crafting.has_recipe("610710001")
    # the other race's item is still explained when it is the only recipe there is
    assert len(crafting.recipes_of("115030021", _prices(), race="Elyos")) == 1
    both = next(k for k in {r["key"] for r in recipes.SINGLES}
                if {r["race"] for r in recipes.recipes_for(k)} >= {"Elyos", "Asmodians"})
    assert {r["race"] for r in crafting.recipes_of(both, {})} >= {"Elyos", "Asmodians"}
    assert "Asmodians" not in {r["race"] for r in crafting.recipes_of(both, {}, race="Elyos")}


def test_race_follows_the_market():
    elyos_step1 = next(c for c in recipes.CHAINS if c["race"] == "Elyos")["steps"][0]["output"][0]
    assert crafting.detect_race({elyos_step1: {"price": 1, "count": 1}}) == "Elyos"
    assert crafting.detect_race({GUARD["steps"][0]["output"][0]: {"price": 1, "count": 1}}) == "Asmodians"
    assert crafting.detect_race({}) is None


def test_parse_page_reads_recipe_cards():
    card = ('<article><div><a class="x" href="/db/items/610710001">Orichalcum Ingot</a></div><div><span>×10</span>'
            '<span>Materials</span><span>Mastery<!-- --> <!-- -->25</span></div><div><div>Materials</div><div>'
            '<a href="/db/items/610620013"><img src="a.webp"/><span>Orichalcum Ore</span><span>×<!-- -->20</span></a>'
            '<a href="/db/items/630541001"><img src="b.webp"/><span>Orichalcum Solvent (Bound)</span><span>×<!-- -->10</span></a>'
            '</div></div></article>')
    [r] = recipes.parse_page(card, "Blacksmithing")
    assert (r["key"], r["qty"], r["mastery"], r["race"], r["category"]) == ("610710001", 10, 25, None, "Materials")
    assert r["materials"] == [["610620013", "Orichalcum Ore", 20], ["630541001", "Orichalcum Solvent (Bound)", 10]]
