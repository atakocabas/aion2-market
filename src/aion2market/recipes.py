"""Every crafting recipe, for buy-or-craft and craft-and-sell decisions.

The recipes (materials and quantities per attempt, output quantity, mastery, race) live in
recipe_data.py, generated from aion2.app's crafting database, which takes them from NC's game data:

    python -m aion2market.recipes update      # refetch (slowly, a page a second) and rewrite recipe_data.py

Equipment recipes form 4-step chains: each step consumes the previous step's Splendent (combo)
result, so ``tries`` is the expected number of attempts for that combo (25 % combo proc per step;
the last step also has a normal result at ~1.06 tries). Everything else (potions, food, scrolls,
manastones, intermediate materials) is a single recipe. Item keys are the market's game_item_key;
Elyos and Asmodian items have different keys, so each race has its own chains.
"""
from __future__ import annotations

import argparse
import html
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

from .recipe_data import RECIPES

STEP_TRIES = {1: 4.295471, 2: 4.226813, 3: 4.130642, 4: 4.226543}
LAST_NORMAL_TRIES = 1.056636
EQUIPMENT_PREFIXES = ("1", "2", "3")        # weapons, armor, accessories; materials and consumables start with 5/6
COMBO_KEY_STEP = 2                          # Star Dragon Lord 110230019 -> Splendent Star Dragon Lord 110230021


def is_equipment(key: str) -> bool:
    return key.startswith(EQUIPMENT_PREFIXES)


def is_npc_item(name: str) -> bool:
    """Bound shop materials (bottles, ink, solvents, spices): bought from an NPC, never on the market."""
    return name.endswith("(Bound)")


def _chain_of(group: list[dict]) -> dict | None:
    """One race's recipes for one equipment slot, as a chain, or None if they don't link up."""
    group = sorted(group, key=lambda r: r["mastery"])
    inputs = [[m for m in r["materials"] if is_equipment(m[0])] for r in group]
    if len(group) < 2 or inputs[0] or any(len(i) != 1 for i in inputs[1:]):
        return None
    steps = []
    for n, r in enumerate(group, 1):
        mats = [tuple(m) for m in r["materials"] if not is_equipment(m[0])]
        step = {"step": n, "tries": STEP_TRIES.get(n, STEP_TRIES[4]), "materials": mats, "mastery": r["mastery"]}
        if n < len(group):
            key, name, _ = inputs[n][0]               # the next step consumes this step's combo result
            step["output"] = (key, name)
        else:
            step["output"] = (str(int(r["key"]) + COMBO_KEY_STEP), f"Splendent {r['name']}")
            step["normal_output"] = (r["key"], r["name"])
            step["normal_tries"] = LAST_NORMAL_TRIES
        steps.append(step)
    first = group[0]
    return {"slot": first["category"], "profession": first["profession"], "race": first["race"], "steps": steps}


def _build() -> tuple[list[dict], list[dict]]:
    groups = defaultdict(list)
    singles = []
    for r in RECIPES:
        if is_equipment(r["key"]):
            groups[(r["race"], r["category"])].append(r)
        else:
            singles.append(r)
    chains = []
    for group in groups.values():
        chain = _chain_of(group)
        if chain:
            chains.append(chain)
        else:
            singles += group
    order = {"Blacksmithing": 0, "Tailoring": 1, "Jewelcrafting": 2}
    chains.sort(key=lambda c: (order.get(c["profession"], 9), c["slot"], c["race"] or ""))
    return chains, singles


CHAINS, SINGLES = _build()


def recipes_for(key: str) -> list[dict]:
    """Single recipes that make ``key`` (several when races or batch sizes differ)."""
    return _BY_PRODUCT.get(key, [])


_BY_PRODUCT: dict[str, list[dict]] = defaultdict(list)
for _r in SINGLES:
    _BY_PRODUCT[_r["key"]].append(_r)


def all_keys() -> set[str]:
    """Every tradable material and output in the recipes, so their prices are always tracked."""
    keys = set()
    for chain in CHAINS:
        for step in chain["steps"]:
            keys.add(step["output"][0])
            if "normal_output" in step:
                keys.add(step["normal_output"][0])
            keys.update(m[0] for m in step["materials"] if not is_npc_item(m[1]))
    for r in SINGLES:
        if not is_npc_item(r["name"]):
            keys.add(r["key"])
        keys.update(m[0] for m in r["materials"] if not is_npc_item(m[1]))
    return keys


# ---------- updating recipe_data.py from aion2.app ----------

SOURCE = "https://aion2.app/db/crafting?section=craft&group={group}&page={page}"
PROFESSIONS = ["Blacksmithing", "Tailoring", "Jewelcrafting", "Alchemy", "Cooking"]


def parse_page(text: str, profession: str) -> list[dict]:
    """The recipe cards (<article>) of one aion2.app crafting page."""
    out = []
    for art in re.findall(r"<article.*?</article>", text, re.S):
        product = re.search(r'<a [^>]*href="/db/items/(\d+)"[^>]*>([^<]+)</a>', art)
        tags = [html.unescape(t.replace("<!-- -->", "")).strip()
                for t in re.findall(r"<span[^>]*>((?:[^<]|<!-- -->)*)</span>", art[:art.find("Materials</div>")])]
        mats = [[k, html.unescape(n), int(q)] for k, n, q in re.findall(
            r'href="/db/items/(\d+)"><img[^>]*/><span[^>]*>([^<]+)</span><span[^>]*>[^<]*?(?:<!-- -->)?(\d+)</span>', art)]
        if not product or not mats:
            continue
        qty = next((int(t[1:]) for t in tags if re.fullmatch(r"[×x]\d+", t)), 1)
        mastery = next((int(t.split()[-1]) for t in tags if t.startswith("Mastery")), 0)
        race = next((t for t in tags if t in ("Elyos", "Asmodians")), None)
        category = next((t for t in tags if not re.fullmatch(r"[×x]\d+", t) and not t.startswith("Mastery")
                         and t not in ("Elyos", "Asmodians")), "")
        out.append({"key": product.group(1), "name": html.unescape(product.group(2)).strip(),
                    "profession": profession, "category": category, "mastery": mastery, "race": race,
                    "qty": qty, "materials": mats})
    return out


def fetch_all(delay: float = 1.0, progress=print) -> list[dict]:
    recipes = []
    for profession in PROFESSIONS:
        seen_first = None
        for page in range(1, 50):
            req = urllib.request.Request(SOURCE.format(group=profession, page=page),
                                         headers={"User-Agent": "aion2market (recipes)"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                found = parse_page(resp.read().decode("utf-8"), profession)
            time.sleep(delay)
            if not found or (seen_first is not None and found[0] == seen_first):
                break                                  # past the last page (the site repeats page 1)
            seen_first = seen_first or found[0]
            recipes += found
            progress(f"{profession} sayfa {page}: {len(found)} tarif")
    unique = {}
    for r in recipes:
        unique[(r["key"], r["race"], r["qty"], tuple(map(tuple, r["materials"])))] = r
    return sorted(unique.values(), key=lambda r: (r["profession"], r["category"], r["mastery"], r["key"], r["race"] or ""))


def write_data(recipes: list[dict], path: Path = Path(__file__).with_name("recipe_data.py")) -> None:  # noqa: B008 (Path is immutable)
    lines = ['"""Generated by `python -m aion2market.recipes update` from aion2.app\'s crafting database. Do not edit."""',
             "", "RECIPES = ["]
    lines += [f"    {r!r}," for r in recipes]
    lines += ["]", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crafting tariflerini aion2.app'ten günceller.")
    ap.add_argument("action", choices=["update"])
    ap.parse_args(argv)
    recipes = fetch_all()
    write_data(recipes)
    print(f"{len(recipes)} tarif yazıldı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
