"""Buy-or-craft: the cheapest way to own each tier of a crafting chain at current market prices.

For every tier: best = min(buy it on the market, best previous tier + this step's expected material
cost). Materials use the cheaper of buying them and buying the matching Odyle to morph (1:1).
"""
from __future__ import annotations

from .dashboard import ODYLE_MORPHS
from .recipes import CHAINS


def material_cost(key: str, prices: dict[str, dict]) -> dict | None:
    """Cheapest way to get one unit: {'price', 'via': 'market'|'odyle', 'via_key'} or None if unpriced."""
    options = []
    if key in prices:
        options.append((prices[key]["price"], "market", key))
    odyle = ODYLE_MORPHS.get(key)
    if odyle and odyle in prices:
        options.append((prices[odyle]["price"], "odyle", odyle))
    if not options:
        return None
    price, via, via_key = min(options)
    return {"price": price, "via": via, "via_key": via_key}


def _step_cost(step: dict, prices: dict[str, dict]) -> tuple[float | None, list[dict]]:
    """Material cost of one attempt, and the material lines (missing prices make the cost None)."""
    lines, total = [], 0.0
    for key, name, qty in step["materials"]:
        mc = material_cost(key, prices)
        lines.append({"item_key": key, "name": name, "qty": qty, **(mc or {"price": None, "via": None})})
        total = None if mc is None or total is None else total + mc["price"] * qty
    return total, lines


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


def plan(prices: dict[str, dict], fee_pct: float = 12.0, lang: str = "tr") -> list[dict]:
    """prices: item_key -> {'price', 'count'} for items listed right now."""
    out = []
    for chain in CHAINS:
        steps, prev = [], None
        for step in chain["steps"]:
            attempt, lines = _step_cost(step, prices)
            tier = _tier(step["output"], step["tries"], attempt, prev, prices, fee_pct)
            entry = {"step": step["step"], "materials": lines, "result": tier}
            if "normal_output" in step:
                entry["normal_result"] = _tier(step["normal_output"], step["normal_tries"], attempt, prev,
                                               prices, fee_pct)
            steps.append(entry)
            prev = tier
        out.append({"slot": chain["slot"], "profession": chain["profession"], "steps": steps,
                    "route": route(steps, lang)})
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
        return "Craft from scratch (steps 1-4)" if en else "Baştan üret (1-4. adımlar)"
    bought = steps[first_crafted - 2]["result"]["name"]
    if en:
        todo = f"step {first_crafted}" if first_crafted == len(steps) else f"steps {first_crafted}-{len(steps)}"
        return f"Buy {bought}, craft {todo}"
    todo = f"{first_crafted}. adımı" if first_crafted == len(steps) else f"{first_crafted}-{len(steps)}. adımları"
    return f"{bought} al, {todo} üret"
