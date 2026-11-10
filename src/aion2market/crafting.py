"""Buy-or-craft and craft-and-sell at current market prices, for every recipe in recipes.py.

Chains (equipment): for every tier, best = min(buy it on the market, best previous tier + this step's
expected material cost). Single recipes (potions, food, scrolls, materials): the cost of one craft
against what its output sells for after the market fee.

A material costs the cheapest of: buying it, buying the matching Odyle to morph (1:1), or crafting it
from its own recipe. Bound shop materials come from an NPC; their price isn't known, so they count as
0 and the result is marked.
"""
from __future__ import annotations

from .dashboard import ODYLE_MORPHS
from .recipes import CHAINS, SINGLES, is_npc_item, recipes_for

MAX_DEPTH = 3                 # material -> its recipe -> its materials ...


def material_cost(key: str, prices: dict[str, dict], name: str = "", _seen: frozenset = frozenset()) -> dict | None:
    """Cheapest way to get one unit: {'price', 'via': 'market'|'odyle'|'craft'|'npc', 'via_key'}, or None."""
    options = []
    if key in prices:
        options.append((prices[key]["price"], "market", key))
    odyle = ODYLE_MORPHS.get(key)
    if odyle and odyle in prices:
        options.append((prices[odyle]["price"], "odyle", odyle))
    if len(_seen) < MAX_DEPTH and key not in _seen:
        for r in recipes_for(key):
            cost, _, npc = recipe_cost(r, prices, _seen | {key})
            if cost is not None:
                options.append((cost / r["qty"], "craft", key) if not npc else (cost / r["qty"], "craft_npc", key))
    if not options:
        return {"price": 0.0, "via": "npc", "via_key": key} if is_npc_item(name) else None
    price, via, via_key = min(options)
    return {"price": price, "via": via, "via_key": via_key}


def recipe_cost(recipe: dict, prices: dict[str, dict], _seen: frozenset = frozenset()) -> tuple[float | None, list[dict], bool]:
    """(material cost of one craft, material lines, whether NPC materials were left out)."""
    lines: list[dict] = []
    total: float | None = 0.0
    npc = False
    for key, name, qty in recipe["materials"]:
        mc = material_cost(key, prices, name, _seen)
        lines.append({"item_key": key, "name": name, "qty": qty, **(mc or {"price": None, "via": None})})
        total = None if mc is None or total is None else total + mc["price"] * qty
        npc = npc or (mc is not None and mc["via"] in ("npc", "craft_npc"))
    return total, lines, npc


def _step_cost(step: dict, prices: dict[str, dict]) -> tuple[float | None, list[dict], bool]:
    return recipe_cost({"materials": step["materials"]}, prices)


def _tier(output: tuple[str, str], tries: float, attempt_cost: float | None, prev_best: dict | None,
          prices: dict[str, dict], fee_pct: float) -> dict:
    key, name = output
    market = prices.get(key, {}).get("price")
    prev_exact = prev_best["exact_cost"] if prev_best else 0        # unrounded, so errors don't pile up
    craft = None if attempt_cost is None or prev_exact is None else attempt_cost * tries + prev_exact
    options = [(c, how) for c, how in ((market, "buy"), (craft, "craft")) if c is not None]
    cost, how = min(options) if options else (None, None)
    return {
        "item_key": key, "name": name, "tries": tries,
        "attempt_cost": None if attempt_cost is None else round(attempt_cost),
        "expected_material_cost": None if attempt_cost is None else round(attempt_cost * tries),
        "market_price": market, "listings": prices.get(key, {}).get("count"),
        "craft_cost": None if craft is None else round(craft),          # from the best previous tier
        "best": how, "cost": None if cost is None else round(cost), "exact_cost": cost,
        # crafting it (via the best route) and selling it, after the market fee
        "sell_profit": None if craft is None or market is None else round(market * (1 - fee_pct / 100) - craft),
    }


def detect_race(prices: dict[str, dict]) -> str | None:
    """Elyos and Asmodian equipment have different keys; the market shows one side's."""
    seen = {"Elyos": 0, "Asmodians": 0}
    for chain in CHAINS:
        for step in chain["steps"]:
            seen[chain["race"]] += step["output"][0] in prices
    return max(seen, key=seen.__getitem__) if any(seen.values()) else None


def plan(prices: dict[str, dict], fee_pct: float = 12.0, lang: str = "tr", race: str | None = None) -> list[dict]:
    """prices: item_key -> {'price', 'count'} for items listed right now. Chains of ``race`` (all if None)."""
    return [_plan_chain(chain, prices, fee_pct, lang) for chain in CHAINS if not race or chain["race"] == race]


def _plan_chain(chain: dict, prices: dict[str, dict], fee_pct: float, lang: str) -> dict:
    steps, prev, npc = [], None, False
    for step in chain["steps"]:
        attempt, lines, step_npc = _step_cost(step, prices)
        npc = npc or step_npc
        tier = _tier(step["output"], step["tries"], attempt, prev, prices, fee_pct)
        entry = {"step": step["step"], "materials": lines, "result": tier, "npc": step_npc}
        if "normal_output" in step:
            entry["normal_result"] = _tier(step["normal_output"], step["normal_tries"], attempt, prev,
                                           prices, fee_pct)
        steps.append(entry)
        prev = tier
    return {"slot": chain["slot"], "profession": chain["profession"], "race": chain["race"],
            "steps": steps, "route": route(steps, lang), "npc": npc}


# Chain results by item key: (chain, step index, whether it is the last step's normal result).
_CHAIN_RESULTS: dict[str, list[tuple[dict, int, bool]]] = {}
for _chain in CHAINS:
    for _i, _step in enumerate(_chain["steps"]):
        _CHAIN_RESULTS.setdefault(_step["output"][0], []).append((_chain, _i, False))
        if "normal_output" in _step:
            _CHAIN_RESULTS.setdefault(_step["normal_output"][0], []).append((_chain, _i, True))


def has_recipe(key: str) -> bool:
    return key in _CHAIN_RESULTS or bool(recipes_for(key))


def _material_lines(lines: list[dict]) -> list[dict]:
    return [{"item_key": m["item_key"], "name": m["name"], "qty": m["qty"], "price": m["price"], "via": m["via"],
             "has_recipe": has_recipe(m["item_key"])} for m in lines]


def recipes_of(key: str, prices: dict[str, dict], fee_pct: float = 12.0, race: str | None = None) -> list[dict]:
    """Every way to craft ``key`` (a single recipe's output or any tier of an equipment chain), priced
    like plan() and singles(). With a ``race``, the other race's recipes are left out unless they are
    the only ones."""
    out = []
    for chain, i, normal in _CHAIN_RESULTS.get(key, []):
        steps = _plan_chain(chain, prices, fee_pct, "en")["steps"]
        tier = steps[i]["normal_result" if normal else "result"]
        npc_before = False            # NPC materials on the cheapest route to the previous tier
        for s in steps[:i]:
            npc_before = s["result"]["best"] == "craft" and (s["npc"] or npc_before)
        materials = _material_lines(steps[i]["materials"])
        if i:
            # The previous tier's result is consumed too, once per finished item (not per attempt), and
            # it costs whatever its own cheapest route does.
            prev = steps[i - 1]["result"]
            via = {"buy": "market", "craft": "craft_npc" if npc_before else "craft"}.get(prev["best"])
            materials.insert(0, {"item_key": prev["item_key"], "name": prev["name"], "qty": 1,
                                 "price": prev["exact_cost"], "via": via, "has_recipe": True})
        out.append({"profession": chain["profession"], "category": chain["slot"],
                    "mastery": chain["steps"][i]["mastery"], "race": chain["race"], "qty": 1,
                    "combo": not normal, "tries": tier["tries"], "materials": materials,
                    "cost": tier["attempt_cost"], "unit_cost": tier["craft_cost"],
                    "market_price": tier["market_price"],
                    "npc": steps[i]["npc"] or npc_before})
    for r in recipes_for(key):
        cost, lines, npc = recipe_cost(r, prices)
        out.append({"profession": r["profession"], "category": r["category"], "mastery": r["mastery"],
                    "race": r["race"], "qty": r["qty"], "combo": False, "tries": None,
                    "materials": _material_lines(lines),
                    "cost": None if cost is None else round(cost),
                    "unit_cost": None if cost is None else round(cost / r["qty"]),
                    "market_price": prices.get(key, {}).get("price"), "npc": npc})
    mine = [r for r in out if r["race"] in (race, None)] if race else out
    return mine or out


def singles(prices: dict[str, dict], fee_pct: float = 12.0, race: str | None = None) -> list[dict]:
    """Craft-and-sell for every single recipe whose output can be sold, most profitable first."""
    out = []
    for r in SINGLES:
        if (race and r["race"] not in (race, None)) or is_npc_item(r["name"]):
            continue
        cost, lines, npc = recipe_cost(r, prices)
        market = prices.get(r["key"], {}).get("price")
        revenue = None if market is None else market * r["qty"] * (1 - fee_pct / 100)
        profit = None if cost is None or revenue is None else revenue - cost
        out.append({
            "item_key": r["key"], "name": r["name"], "profession": r["profession"], "category": r["category"],
            "mastery": r["mastery"], "qty": r["qty"], "materials": lines, "npc": npc,
            "cost": None if cost is None else round(cost),
            "unit_cost": None if cost is None else round(cost / r["qty"]),
            "market_price": market, "listings": prices.get(r["key"], {}).get("count"),
            "revenue": None if revenue is None else round(revenue),
            "profit": None if profit is None else round(profit),
            "profit_pct": None if profit is None or not cost else round(profit / cost * 100, 1),
        })
    out.sort(key=lambda x: (x["profit"] is None, -(x["profit"] or 0)))
    return out


def route(steps: list[dict], lang: str = "tr") -> str:
    """Plain-language cheapest way to the final (combo) item, e.g. 'Artisan's'ı al, 4. adımı üret'."""
    en = lang == "en"
    final = steps[-1]["result"]
    if final["cost"] is None:
        return "Prices missing" if en else "Fiyat eksik"
    if final["best"] == "buy":
        return "Buy it ready-made" if en else "Hazır al"
    first_crafted = len(steps)
    for i in range(len(steps) - 1, -1, -1):
        if steps[i]["result"]["best"] == "craft":
            first_crafted = i + 1
        else:
            break
    if first_crafted == 1:
        return f"Craft from scratch (steps 1-{len(steps)})" if en else f"Baştan üret (1-{len(steps)}. adımlar)"
    bought = steps[first_crafted - 2]["result"]["name"]
    if en:
        todo = f"step {first_crafted}" if first_crafted == len(steps) else f"steps {first_crafted}-{len(steps)}"
        return f"Buy {bought}, craft {todo}"
    todo = f"{first_crafted}. adımı" if first_crafted == len(steps) else f"{first_crafted}-{len(steps)}. adımları"
    return f"{bought} al, {todo} üret"
