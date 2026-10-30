"""Crafting chains for buy-or-craft decisions.

Taken from a community crafting sheet (Mastery 100). Each step upgrades the previous tier's item;
the listed materials are what one attempt consumes. ``tries`` is the expected number of attempts
for that step's result (25 % combo proc per step; step 4 also has a normal result at ~1.06 tries).
Item keys are the market's game_item_key (Asmodian / EU ids).
"""
from __future__ import annotations

ODYLE, FINE_ODYLE, PURE_ODYLE, RADIANT_ODYLE = "610610013", "610610014", "610610015", "610610016"
REFINING_STONE, EXPERT_STONE, ARTISAN_STONE, ULTIMATE_STONE = "610530001", "610530005", "610530008", "610530010"
WRATHFUL_MIND = "610511013"

STEP_TRIES = {1: 4.295471, 2: 4.226813, 3: 4.130642, 4: 4.226543}
STEP4_NORMAL_TRIES = 1.056636


def _chain(slot, profession, outputs, step_materials):
    """outputs: (tier1, tier2, tier3, tier4 normal, tier4 combo) as (key, name)."""
    t1, t2, t3, t4n, t4c = outputs
    return {
        "slot": slot, "profession": profession,
        "steps": [
            {"step": 1, "output": t1, "tries": STEP_TRIES[1], "materials": step_materials[0]},
            {"step": 2, "output": t2, "tries": STEP_TRIES[2], "materials": step_materials[1]},
            {"step": 3, "output": t3, "tries": STEP_TRIES[3], "materials": step_materials[2]},
            {"step": 4, "output": t4c, "tries": STEP_TRIES[4], "materials": step_materials[3],
             "normal_output": t4n, "normal_tries": STEP4_NORMAL_TRIES},
        ],
    }


# materials per step: (item key, name, quantity per attempt)
CHAINS = [
    _chain("Guard", "Blacksmithing",
           (("115050016", "Splendent Orichalcum Guard"), ("115040014", "Expert's Splendent Orichalcum Guard"),
            ("115030014", "Artisan's Splendent Orichalcum Guard"), ("115030019", "Star Dragon Lord Guard"),
            ("115030021", "Splendent Star Dragon Lord Guard")),
           [[("610710001", "Orichalcum Ingot", 3), (REFINING_STONE, "Refining Stone", 5), (ODYLE, "Odyle", 2)],
            [(EXPERT_STONE, "Expert's Refining Stone", 5), ("610620014", "Fine Orichalcum Ore", 6),
             (FINE_ODYLE, "Fine Odyle", 3)],
            [(ARTISAN_STONE, "Artisan's Refining Stone", 5), ("610620015", "Pure Orichalcum Ore", 8),
             (PURE_ODYLE, "Pure Odyle", 4)],
            [(ULTIMATE_STONE, "Artisan's Ultimate Refining Stone", 4), ("610710006", "Fine Thick Balaur Horn", 22),
             (WRATHFUL_MIND, "Wrathful Mind", 10), ("610620016", "Radiant Orichalcum Ore", 9),
             (RADIANT_ODYLE, "Radiant Odyle", 5)]]),
    _chain("Earring", "Jewelcrafting",
           (("310250012", "Splendent Diamond Earrings"), ("310240014", "Expert's Splendent Diamond Earrings"),
            ("310230014", "Artisan's Splendent Diamond Earrings"), ("310230019", "Star Dragon Lord Earrings"),
            ("310230021", "Splendent Star Dragon Lord Earrings")),
           [[("610730020", "Diamond Decoration", 1), (REFINING_STONE, "Refining Stone", 3), (ODYLE, "Odyle", 1)],
            [(EXPERT_STONE, "Expert's Refining Stone", 3), ("610660029", "Fine Diamond Gemstone", 3),
             (FINE_ODYLE, "Fine Odyle", 2)],
            [(ARTISAN_STONE, "Artisan's Refining Stone", 3), ("610660032", "Pure Diamond Gemstone", 4),
             (PURE_ODYLE, "Pure Odyle", 2)],
            [(ULTIMATE_STONE, "Artisan's Ultimate Refining Stone", 2),
             ("610730022", "Enhanced Thick Balaur Scale", 11), (WRATHFUL_MIND, "Wrathful Mind", 5),
             ("610660035", "Radiant Diamond Gemstone", 5), (RADIANT_ODYLE, "Radiant Odyle", 2)]]),
    _chain("Ring", "Jewelcrafting",
           (("310350012", "Splendent Sapphire Ring"), ("310340014", "Expert's Splendent Sapphire Ring"),
            ("310330014", "Artisan's Splendent Sapphire Ring"), ("310330019", "Star Dragon Lord Ring"),
            ("310330021", "Splendent Star Dragon Lord Ring")),
           [[("610730016", "Sapphire Decoration", 1), (REFINING_STONE, "Refining Stone", 2), (ODYLE, "Odyle", 1)],
            [(EXPERT_STONE, "Expert's Refining Stone", 2), ("610660028", "Fine Sapphire Gemstone", 2),
             (FINE_ODYLE, "Fine Odyle", 1)],
            [(ARTISAN_STONE, "Artisan's Refining Stone", 2), ("610660031", "Pure Sapphire Gemstone", 3),
             (PURE_ODYLE, "Pure Odyle", 1)],
            [(ULTIMATE_STONE, "Artisan's Ultimate Refining Stone", 2),
             ("610730022", "Enhanced Thick Balaur Scale", 8), (WRATHFUL_MIND, "Wrathful Mind", 4),
             ("610660034", "Radiant Sapphire Gemstone", 3), (RADIANT_ODYLE, "Radiant Odyle", 2)]]),
    _chain("Necklace", "Jewelcrafting",
           (("310150012", "Splendent Ruby Necklace"), ("310140014", "Expert's Splendent Ruby Necklace"),
            ("310130014", "Artisan's Splendent Ruby Necklace"), ("310130019", "Star Dragon Lord Necklace"),
            ("310130021", "Splendent Star Dragon Lord Necklace")),
           [[("610730021", "Ruby Decoration", 1), (REFINING_STONE, "Refining Stone", 4), (ODYLE, "Odyle", 1)],
            [(EXPERT_STONE, "Expert's Refining Stone", 4), ("610660030", "Fine Ruby Gemstone", 4),
             (FINE_ODYLE, "Fine Odyle", 2)],
            [(ARTISAN_STONE, "Artisan's Refining Stone", 4), ("610660033", "Pure Ruby Gemstone", 5),
             (PURE_ODYLE, "Pure Odyle", 2)],
            [(ULTIMATE_STONE, "Artisan's Ultimate Refining Stone", 3),
             ("610730022", "Enhanced Thick Balaur Scale", 14), (WRATHFUL_MIND, "Wrathful Mind", 6),
             ("610660036", "Radiant Ruby Gemstone", 6), (RADIANT_ODYLE, "Radiant Odyle", 2)]]),
    _chain("Mace", "Blacksmithing",
           (("110750016", "Splendent Orichalcum Mace"), ("110740014", "Expert's Splendent Orichalcum Mace"),
            ("110730014", "Artisan's Splendent Orichalcum Mace"), ("110730019", "Star Dragon Lord Mace"),
            ("110730021", "Splendent Star Dragon Lord Mace")),
           [[("610710001", "Orichalcum Ingot", 3), (REFINING_STONE, "Refining Stone", 5), (ODYLE, "Odyle", 2)],
            [(EXPERT_STONE, "Expert's Refining Stone", 5), ("610620014", "Fine Orichalcum Ore", 6),
             (FINE_ODYLE, "Fine Odyle", 3)],
            [(ARTISAN_STONE, "Artisan's Refining Stone", 5), ("610620015", "Pure Orichalcum Ore", 8),
             (PURE_ODYLE, "Pure Odyle", 4)],
            [(ULTIMATE_STONE, "Artisan's Ultimate Refining Stone", 4), ("610710006", "Fine Thick Balaur Horn", 22),
             (WRATHFUL_MIND, "Wrathful Mind", 10), ("610620016", "Radiant Orichalcum Ore", 9),
             (RADIANT_ODYLE, "Radiant Odyle", 5)]]),
]


def all_keys() -> set[str]:
    """Every material and output in the chains, so their prices are always tracked."""
    keys = set()
    for chain in CHAINS:
        for step in chain["steps"]:
            keys.add(step["output"][0])
            if "normal_output" in step:
                keys.add(step["normal_output"][0])
            keys.update(m[0] for m in step["materials"])
    return keys
