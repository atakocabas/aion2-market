"""Local web UI: every item's price and how much it changed since the previous
market listing, over 7 days and over 30 days.

    python -m aion2market.dashboard            # http://127.0.0.1:8765

Only listens on 127.0.0.1 and only touches data/market.db (item names and the
watchlist are the only things it writes).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import time
import urllib.parse
import webbrowser
from collections import Counter, defaultdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import __version__, updates
from .market import sell_fee_pct
from .store import Store

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAY = 86400.0
# Opening the market and then an item gives several snapshots seconds apart;
# anything closer than this to the current value counts as the same listing.
SESSION_GAP = 300.0
# A market scan covers at least this share of the items seen in the last 30 days; an item missing from
# the newest scan isn't for sale. Item searches and small shared updates only tell about their own items.
SCAN_SHARE = 0.5
WINDOWS = {"week": 7 * DAY, "month": 30 * DAY}
SPARK_POINTS = 40
# Bogus listings (a lone 10,000,000 placeholder, a mistyped 1 kinah) would otherwise dominate the
# changes. A price counts as an outlier when it is above HIGH x or below 1/LOW x the item's 30-day
# median; items with fewer than MIN_POINTS recent prices are left alone.
OUTLIER_HIGH = 3.0
OUTLIER_LOW = 4.0
OUTLIER_MIN_POINTS = 5
# The reference price everything is compared with ("7 gün ort." in the UI): the mean of the last
# TYPICAL_DAYS days' prices, outliers left out.
TYPICAL_DAYS = 7
TYPICAL_MIN_POINTS = 3


def typical_bounds(prices: list[float]) -> tuple[float, float, float] | None:
    """(median, lowest normal price, highest normal price), or None with too little data."""
    if len(prices) < OUTLIER_MIN_POINTS:
        return None
    med = statistics.median(prices)
    return med, med / OUTLIER_LOW, med * OUTLIER_HIGH


def typical_price(points: list[tuple[float, float]], now: float) -> float | None:
    """Mean of the last TYPICAL_DAYS days' (ts, price) points, outliers against the 30-day median
    left out; None without a 30-day median or with fewer than TYPICAL_MIN_POINTS such prices."""
    bounds = typical_bounds([p for t, p in points if t >= now - 30 * DAY])
    if not bounds:
        return None
    week = [p for t, p in points if t >= now - TYPICAL_DAYS * DAY and bounds[1] <= p <= bounds[2]]
    return round(statistics.fmean(week), 2) if len(week) >= TYPICAL_MIN_POINTS else None


def _pct(now: float, base: float | None) -> float | None:
    return None if not base else round((now - base) / base * 100, 2)


def _downsample(points: list, n: int) -> list:
    if len(points) <= n:
        return points
    step = (len(points) - 1) / (n - 1)
    return [points[round(i * step)] for i in range(n)]


def _base(series: list[tuple], cutoff: float, current_ts: float) -> tuple[tuple | None, bool]:
    """Value at ``cutoff`` (last point at or before it); if history is shorter, the oldest
    point from an earlier listing, flagged partial."""
    before = [p for p in series if p[0] <= cutoff]
    if before:
        return before[-1], False
    first = series[0]
    return (first, True) if first[0] < current_ts - SESSION_GAP else (None, True)


def last_scan(series: dict[str, list[tuple]], now: float) -> float | None:
    """Time of the newest snapshot of the newest market scan (see SCAN_SHARE), or None without one."""
    recent = [(p[0], key) for key, s in series.items() for p in s if p[0] >= now - 30 * DAY]
    need = max(1, math.ceil(len({key for _, key in recent}) * SCAN_SHARE))
    recent.sort(reverse=True)
    window, newest = Counter(), 0
    for ts, key in recent:
        window[key] += 1
        while recent[newest][0] - ts > SESSION_GAP:
            old = recent[newest][1]
            window[old] -= 1
            if not window[old]:
                del window[old]
            newest += 1
        if len(window) >= need:
            return recent[newest][0]
    return None


def default_server(store: Store) -> int | None:
    """This computer's own market server, else the one with the newest data."""
    servers = store.servers()
    return store.home_server() or (servers[0]["server_id"] if servers else None)


def load_series(store: Store, server_id: int | None) -> dict[str, list[tuple[float, float, int]]]:
    series: dict[str, list[tuple[float, float, int]]] = defaultdict(list)
    for key, ts, price, count in store.db.execute(
            "SELECT item_key, ts, min_unit_price, sale_count FROM price_snapshots WHERE server_id = ? ORDER BY ts",
            (server_id,)):
        series[key].append((ts, price, count))
    return series


def item_rows(store: Store, now: float | None = None, server_id: int | None = None,
              series: dict | None = None) -> dict:
    now = now or time.time()
    server_id = server_id or default_server(store)
    if series is None:
        series = load_series(store, server_id)
    if not series:
        return {"items": [], "latest": None, "first": None, "now": now, "server_id": server_id}

    names = dict(store.named_items())
    info = store.item_info()
    watch = dict(store.watchlist())
    latest = max(s[-1][0] for s in series.values())
    first = min(s[0][0] for s in series.values())
    scan = last_scan(series, now) or latest

    items = []
    for key, s in series.items():
        ts, price, count = s[-1]
        bounds = typical_bounds([p[1] for p in s if p[0] >= now - 30 * DAY])
        if bounds:
            _, lo, hi = bounds
            clean = [p for p in s if lo <= p[1] <= hi]      # bases never come from outliers
            suspect = "high" if price > hi else "low" if price < lo else None
        else:
            clean, suspect = s, None
        # A current price far above normal is a lone bogus listing: no change is shown for it.
        # Far below normal is kept (it may be a real bargain) but flagged.
        current = None if suspect == "high" else price
        prev = next((p for p in reversed(clean) if p[0] < ts - SESSION_GAP), None)
        recent = [p for p in clean if p[0] >= now - 30 * DAY]
        official = info.get(key, {})
        row = {
            "item_key": key, "name": names.get(key) or official.get("name"), "custom_name": key in names,
            "official_name": official.get("name"), "icon": official.get("icon"),
            "grade": official.get("grade"), "grade_name": official.get("grade_name"),
            "category": official.get("category"), "type": official.get("type"),
            # Missing from the newest market scan means nobody sells it now: 0 listings,
            # with the last seen price and count kept for reference.
            "price": price, "count": count if ts >= scan - SESSION_GAP else 0, "last_count": count, "ts": ts,
            "listed": ts >= scan - SESSION_GAP,
            "watched": key in watch, "target": watch.get(key),
            "typical": typical_price([(p[0], p[1]) for p in s], now), "suspect": suspect,
            "median30": bounds[0] if bounds else None,
            # normal (non-outlier) 30-day range and how many days it covers, for the deals page
            "low30": min(p[1] for p in recent) if recent else None,
            "high30": max(p[1] for p in recent) if recent else None,
            "history_days": round((ts - recent[0][0]) / DAY, 1) if recent else 0,
            "prev": {"price": prev[1] if prev else None, "ts": prev[0] if prev else None,
                     "change": _pct(current, prev[1] if prev else None) if current else None,
                     "count": prev[2] if prev else None},
            "spark": [[round(p[0]), p[1]] for p in
                      _downsample([p for p in clean if p[0] >= now - 30 * DAY], SPARK_POINTS)],
        }
        for name, span in WINDOWS.items():
            base, partial = _base(clean, now - span, ts) if clean else (None, True)
            row[name] = {"price": base[1] if base else None, "ts": base[0] if base else None,
                         "change": _pct(current, base[1] if base else None) if current else None,
                         "partial": partial}
        items.append(row)
    return {"items": items, "latest": latest, "first": first, "now": now, "server_id": server_id}


# What makes an item worth buying now; every threshold is shown to the user as a reason.
DEAL_MIN_DISCOUNT = 0.10      # at least 10 % under its 7-day average
DEAL_MIN_DROP = -5.0          # and fell at least 5 % since the previous listing or over 7 days
DEAL_MIN_LISTINGS = 2         # something to actually buy
DEAL_MIN_DAYS = 3.0           # enough history for "normal" to mean something
DEAL_FULL_LIQUIDITY = 10      # listings at which liquidity stops adding to the score
DEAL_SLIDING_FACTOR = 0.6     # a week-long slide may not have bottomed yet; sudden dips rank first


WEEKDAYS = {"tr": ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"],
            "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}

# Texts the API hands to the UI, per language (?lang=tr|en); Turkish is the default.
TEXTS = {
    "tr": {
        "under_avg": "7 gün ortalamasının %{p:.0f} altında",
        "fell_week": "7 günde %{p:.0f} düştü",
        "fell_prev": "son listelemeden beri %{p:.0f} düştü",
        "near_bottom": "30 günün en dibine yakın",
        "flip": "7 gün ortalamasından satarsan vergi sonrası adet başı +{v}",
        "listings": "{n} ilan",
        "suspect_low": "30 günlük medyanın çok altında: fırsat da olabilir, hatalı ilan da",
        "sliding": "Bir haftadır düşüşte; dip daha aşağıda olabilir",
        "check": "En ucuz ilan uydurma görünüyor; 7 gün ortalamasından sat",
        "over_avg": "7 gün ortalamasının %{p:.0f} üstünde",
        "rose_week": "7 günde %{p:.0f} yükseldi",
        "hold": "7 gün ortalamasının %{p:.0f} altında; yükselmesini bekle",
        "normal": "7 gün ortalaması civarında",
        "note_drop": "son listelemede %{p:.0f} düştü",
        "note_bottom": "30 günün dibinde",
        "note_suspect": "hatalı ilan olabilir",
        "note_sliding": "haftadır düşüyor",
    },
    "en": {
        "under_avg": "{p:.0f}% under its 7-day average",
        "fell_week": "fell {p:.0f}% in 7 days",
        "fell_prev": "fell {p:.0f}% since the last listing",
        "near_bottom": "near its 30-day bottom",
        "flip": "selling at the 7-day average nets +{v} each after tax",
        "listings": "{n} listings",
        "suspect_low": "far under the 30-day median: could be a bargain or a mistyped listing",
        "sliding": "Falling for a week; the bottom may be lower",
        "check": "The cheapest listing looks bogus; sell at the 7-day average",
        "over_avg": "{p:.0f}% over its 7-day average",
        "rose_week": "rose {p:.0f}% in 7 days",
        "hold": "{p:.0f}% under its 7-day average; wait for it to recover",
        "normal": "around its 7-day average",
        "note_drop": "dropped {p:.0f}% at the last listing",
        "note_bottom": "at its 30-day bottom",
        "note_suspect": "may be a mistyped listing",
        "note_sliding": "falling all week",
    },
}


def lang_of(value: str | None) -> str:
    return value if value in TEXTS else "tr"


def text(lang: str, key: str, **kw) -> str:
    return TEXTS[lang_of(lang)][key].format(**kw)


def fmt_int(v: float, lang: str) -> str:
    return f"{v:,.0f}".replace(",", "." if lang_of(lang) == "tr" else ",")
PATTERN_MIN_POINTS = 20        # an item needs this many 30-day prices to count in a weekday pattern


def weekday_pattern(series: dict[str, list[tuple]], now: float,
                    min_per_day: int = PATTERN_MIN_POINTS) -> list[float | None]:
    """Typical price per local weekday (Mon..Sun) relative to the week's average, in percent.

    Each price is divided by its own item's 30-day median (outliers dropped), so cheap and expensive
    items weigh the same. Per weekday the ratios are averaged with the top and bottom 10 % cut off (a
    plain median sits at exactly 1.0 because many prices don't move for days), then shown against the
    mean over all days."""
    ratios: list[list[float]] = [[] for _ in range(7)]
    for points in series.values():
        recent = [(t, p) for t, p, *_ in points if t >= now - 30 * DAY]
        bounds = typical_bounds([p for _, p in recent])
        if not bounds or len(recent) < PATTERN_MIN_POINTS:
            continue
        med, lo, hi = bounds
        for t, p in recent:
            if lo <= p <= hi:
                ratios[time.localtime(t).tm_wday].append(p / med)
    means = [_trimmed_mean(r) if len(r) >= min_per_day else None for r in ratios]
    known = [m for m in means if m is not None]
    if not known:
        return [None] * 7
    week = statistics.mean(known)
    return [None if m is None else round((m / week - 1) * 100, 1) for m in means]


def _trimmed_mean(values: list[float], cut: float = 0.1) -> float:
    v = sorted(values)
    k = int(len(v) * cut)
    return statistics.mean(v[k:len(v) - k] or v)


def pattern_summary(pattern: list[float | None], lang: str = "tr") -> dict | None:
    known = [(v, i) for i, v in enumerate(pattern) if v is not None]
    if len(known) < 5:
        return None
    (lo, lo_day), (hi, hi_day) = min(known), max(known)
    days = WEEKDAYS[lang_of(lang)]
    return {"by_day": pattern, "cheapest": days[lo_day], "dearest": days[hi_day],
            "cheapest_day": lo_day, "dearest_day": hi_day, "spread": round(hi - lo, 1)}


# Odyle can be morphed 1:1 into the matching ore / gemstone / log (from the community crafting sheet).
ODYLE_MORPHS = {
    "610620014": "610610014", "610660030": "610610014", "610660029": "610610014", "610660028": "610610014",
    "610620015": "610610015", "610660033": "610610015", "610660032": "610610015", "610660031": "610610015",
    "610620016": "610610016", "610660036": "610610016", "610660035": "610610016", "610660034": "610610016",
    "610650018": "610610016",
}


def morph_table(rows: list[dict], fee_pct: float) -> list[dict]:
    """Material vs. its Odyle: whether morphing beats buying it (for crafting) or yields a profit (for selling)."""
    by_key = {r["item_key"]: r for r in rows}
    out = []
    for mat_key, odyle_key in ODYLE_MORPHS.items():
        mat, odyle = by_key.get(mat_key), by_key.get(odyle_key)
        if not mat or not odyle or not mat["count"] or not odyle["count"]:
            continue
        sell_net = mat["price"] * (1 - fee_pct / 100) - odyle["price"]
        out.append({"material": {k: mat[k] for k in ("item_key", "name", "price", "count", "icon", "grade_name")},
                    "odyle": {k: odyle[k] for k in ("item_key", "name", "price", "count", "icon", "grade_name")},
                    "craft_saving": round(mat["price"] - odyle["price"]),      # buy Odyle + morph instead
                    "sell_profit": round(sell_net),                            # buy Odyle, morph, sell material
                    "sell_profit_pct": round(sell_net / odyle["price"] * 100, 1)})
    return sorted(out, key=lambda m: -m["sell_profit_pct"])


def deals(rows: list[dict], fee_pct: float = 12.0, lang: str = "tr") -> list[dict]:
    """Items currently cheap compared with their own recent history, best first.

    score = discount % x closeness to the 30-day bottom (1.0-1.5) x liquidity (0.5-1.0),
    x DEAL_SLIDING_FACTOR when the price has been sliding all week"""
    out = []
    for r in rows:
        typical, price = r.get("typical"), r["price"]
        if (not r["count"] or r["count"] < DEAL_MIN_LISTINGS or r.get("suspect") == "high"
                or not typical or r.get("history_days", 0) < DEAL_MIN_DAYS):
            continue
        discount = (typical - price) / typical
        drops = [c for c in (r["prev"]["change"], r["week"]["change"]) if c is not None]
        if discount < DEAL_MIN_DISCOUNT or not drops or min(drops) > DEAL_MIN_DROP:
            continue
        low, high = r.get("low30"), r.get("high30")
        position = 0.0 if not low or high is None or high <= low else max(0.0, min(1.0, (price - low) / (high - low)))
        liquidity = min(1.0, r["count"] / DEAL_FULL_LIQUIDITY)
        score = discount * 100 * (1.5 - 0.5 * position) * (0.5 + 0.5 * liquidity)
        reasons = [text(lang, "under_avg", p=discount * 100)]
        if r["week"]["change"] is not None and r["week"]["change"] <= DEAL_MIN_DROP:
            reasons.append(text(lang, "fell_week", p=-r["week"]["change"]))
        if r["prev"]["change"] is not None and r["prev"]["change"] <= DEAL_MIN_DROP:
            reasons.append(text(lang, "fell_prev", p=-r["prev"]["change"]))
        if position <= 0.15:
            reasons.append(text(lang, "near_bottom"))
        # Flip: buy now, sell later at the usual price, after the market's fee.
        net_profit = typical * (1 - fee_pct / 100) - price
        if net_profit > 0:
            reasons.append(text(lang, "flip", v=fmt_int(net_profit, lang)))
        reasons.append(text(lang, "listings", n=r["count"]))
        # The whole last week already well under the month's median: a slide, not a dip.
        sliding = bool(r.get("median30") and typical < r["median30"] * (1 - DEAL_MIN_DISCOUNT * 2))
        warnings = []
        if r.get("suspect") == "low":
            warnings.append(text(lang, "suspect_low"))
        if sliding:
            warnings.append(text(lang, "sliding"))
        warning = " · ".join(warnings) or None
        # One short line for the table: only what its columns don't already show.
        note = []
        if r["prev"]["change"] is not None and r["prev"]["change"] <= DEAL_MIN_DROP:
            note.append({"text": text(lang, "note_drop", p=-r["prev"]["change"])})
        if position <= 0.15:
            note.append({"text": text(lang, "note_bottom")})
        if r.get("suspect") == "low":
            note.append({"text": text(lang, "note_suspect"), "warn": True})
        if sliding:
            note.append({"text": text(lang, "note_sliding"), "warn": True})
        if sliding:
            score *= DEAL_SLIDING_FACTOR
        out.append({**r, "deal": {"score": round(score, 1), "discount": round(discount * 100, 1),
                                  "saving": round(typical - price), "position": round(position, 2),
                                  "reasons": reasons, "warning": warning, "sliding": sliding, "note": note,
                                  "net_profit": round(net_profit),
                                  "profit_pct": round(net_profit / price * 100, 1)}})
    return sorted(out, key=lambda r: -r["deal"]["score"])


SELL_PREMIUM = 0.10     # "sell": at least 10 % above the item's 7-day average ...
SELL_RISE = 15.0        # ... or up at least 15 % over 7 days
HOLD_DISCOUNT = 0.10    # "wait": at least 10 % under that average


def inventory_view(store: Store, server_id: int | None = None, lang: str = "tr") -> dict:
    """The latest inventory priced at this server's current market, with a sell/wait signal per item."""
    ts, owned = store.latest_inventory()
    sid = server_id or default_server(store)
    series = load_series(store, sid)
    rows = {r["item_key"]: r for r in item_rows(store, server_id=sid, series=series)["items"]}
    fee = sell_fee_pct(store)
    pattern = pattern_summary(weekday_pattern(series, time.time()), lang)
    items, unpriced = [], []
    for key, count in owned.items():
        r = rows.get(key)
        if not r or not r["count"]:
            unpriced.append({"item_key": key, "name": store.name(key), "count": count,
                             "last_price": r["price"] if r else None})
            continue
        typical, price = r.get("typical"), r["price"]
        bogus = r.get("suspect") == "high"          # a lone silly listing is not a price you can sell at
        sell_price = typical if bogus and typical else price
        premium = (price - typical) / typical if typical and not bogus else None
        week = r["week"]["change"]
        if bogus:
            signal, why = "check", text(lang, "check")
        elif (premium is not None and premium >= SELL_PREMIUM) or (week is not None and week >= SELL_RISE):
            signal = "sell"
            why = text(lang, "over_avg", p=premium * 100) if premium is not None and premium >= SELL_PREMIUM \
                else text(lang, "rose_week", p=week)
        elif premium is not None and premium <= -HOLD_DISCOUNT:
            signal, why = "hold", text(lang, "hold", p=-premium * 100)
        else:
            signal, why = "normal", text(lang, "normal")
        items.append({**r, "owned": count, "premium": None if premium is None else round(premium * 100, 1),
                      "signal": signal, "why": why,
                      # undercut the cheapest listing by one, unless that listing is bogus
                      "suggest_price": max(1, round(sell_price) - (0 if bogus else 1)),
                      "value_net": round(count * sell_price * (1 - fee / 100))})
    return {"ts": ts, "fee_pct": fee, "server_id": sid, "weekdays": pattern, "items": items,
            "unpriced": sorted(unpriced, key=lambda u: -(u["count"])),
            "total_value": sum(i["value_net"] for i in items),
            "sell_value": sum(i["value_net"] for i in items if i["signal"] == "sell")}


def crafting_view(store: Store, server_id: int | None = None, lang: str = "tr") -> dict:
    """Buy-or-craft for every chain and craft-and-sell for every single recipe, at this server's prices."""
    from .crafting import detect_race, plan, singles
    rows = item_rows(store, server_id=server_id)
    # Only items on the market now, and never a bogus far-above-normal listing as "the price".
    prices = {r["item_key"]: {"price": r["price"], "count": r["count"]} for r in rows["items"]
              if r["count"] and r.get("suspect") != "high"}
    info = store.item_info()
    fee = sell_fee_pct(store)
    race = detect_race(prices) or detect_race({r["item_key"]: r for r in rows["items"]})
    chains = plan(prices, fee, lang, race)
    recipes = singles(prices, fee, race)

    def decorate(x):
        x["icon"] = info.get(x["item_key"], {}).get("icon")
        x["grade_name"] = info.get(x["item_key"], {}).get("grade_name")

    best_sales = []
    for chain in chains:
        for step in chain["steps"]:
            for key in ("result", "normal_result"):
                t = step.get(key)
                if not t:
                    continue
                decorate(t)
                if t["sell_profit"] and t["sell_profit"] > 0:
                    best_sales.append({"slot": chain["slot"], "step": step["step"], **t, "npc": chain["npc"],
                                       "profit_pct": round(t["sell_profit"] / t["craft_cost"] * 100, 1)})
            for m in step["materials"]:
                decorate(m)
    for r in recipes:
        decorate(r)
        for m in r["materials"]:
            decorate(m)
        if r["profit"] and r["profit"] > 0:
            best_sales.append({**r, "slot": r["category"], "step": None, "craft_cost": r["cost"],
                               "market_price": r["market_price"], "sell_profit": r["profit"]})
    return {"chains": chains, "recipes": recipes, "race": race, "fee_pct": fee, "server_id": rows["server_id"],
            "latest": rows["latest"], "best_sales": sorted(best_sales, key=lambda t: -t["sell_profit"])}


def item_detail(store: Store, key: str, server_id: int | None = None, lang: str = "tr") -> dict:
    server_id = server_id or default_server(store)
    history = store.snapshot_history(key, 0, server_id)
    ts, listings = store.latest_listings(key, server_id)
    state = store.watch_state(key)
    custom = dict(store.named_items()).get(key)
    bounds = typical_bounds([p for t, p, _ in history if t >= time.time() - 30 * DAY])
    return {
        "item_key": key, "name": store.name(key), "custom_name": custom is not None,
        "info": store.item_info().get(key),
        "typical": {"median": bounds[0], "low": bounds[1], "high": bounds[2],
                    "avg7": typical_price([(t, p) for t, p, _ in history], time.time())} if bounds else None,
        "weekdays": pattern_summary(weekday_pattern({key: history}, time.time(), min_per_day=6), lang),
        "history": [[t, p, c] for t, p, c in history],
        "searches": [[t, n, u, s] for t, n, u, s in store.listing_history(key, 0, server_id)],
        "ranges": [list(r) for r in store.ranges(key, server_id, time.time() - 31 * DAY)] if server_id else [],
        "listings": {"ts": ts or None, "rows": [[q, s, u] for q, s, u in listings[:20]], "total": len(listings)},
        "watch": {"target": state[0]} if state else None,
    }


EXCLUDE_KEY = "ui.exclude"


def clean_exclude(data) -> dict:
    """Validated hide settings: rules match on grade AND category (an empty list matches anything);
    items are hidden one by one."""
    def strings(v, limit, size=60):
        return [str(x)[:size] for x in v if isinstance(x, str) and x.strip()][:limit] if isinstance(v, list) else []
    data = data if isinstance(data, dict) else {}
    rules = []
    for r in data.get("rules", [])[:50] if isinstance(data.get("rules"), list) else []:
        if isinstance(r, dict):
            rule = {"grades": strings(r.get("grades"), 20), "categories": strings(r.get("categories"), 100)}
            if rule["grades"] or rule["categories"]:
                rules.append(rule)
    items = [k for k in strings(data.get("items"), 2000, 12) if k.isdigit()]
    return {"rules": rules, "items": items, "show_hidden": bool(data.get("show_hidden"))}


def get_exclude(store: Store) -> dict:
    try:
        return clean_exclude(json.loads(store.get_meta(EXCLUDE_KEY, "{}")))
    except ValueError:
        return clean_exclude({})


def sync_status(store: Store) -> dict:
    """What the UI shows about the shared store: whether there is one, whether it's on and when it last synced."""
    from . import sync
    last = store.get_meta("sync.last_ok")
    return {"configured": bool(sync.share_url(store)), "enabled": sync.enabled(store),
            "last_ok": float(last) if last else None, "last_error": store.get_meta("sync.last_error")}


def npcap_status(store: Store | None = None) -> dict:
    """Whether live capture is possible and working: without Npcap the app only has the background sources.
    ``error`` is why live capture isn't running (no key file yet, capture failed); ``names_error`` why
    official item names can't be looked up on this computer."""
    from .app import NPCAP_URL, npcap_installed
    status = {"installed": npcap_installed(), "url": NPCAP_URL}
    if store is not None:
        status |= {"error": store.get_meta("capture.error"), "names_error": store.get_meta("iteminfo.last_error")}
    return status


def db_path() -> Path:
    return Path(os.environ.get("AION2_DB") or PROJECT_ROOT / "data" / "market.db")


class Handler(BaseHTTPRequestHandler):
    server_version = "aion2market"

    def log_message(self, fmt, *args):      # keep the console quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _host_ok(self) -> bool:
        # Blocks DNS-rebinding: only our own address may be used to reach us.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._host_ok():
            return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
        path, _, query = self.path.partition("?")
        params = urllib.parse.parse_qs(query)
        server = params.get("server", [""])[0]
        server_id = int(server) if server.isdigit() else None
        lang = lang_of(params.get("lang", [""])[0])
        if path in ("/", "/index.html"):
            html = resources.files("aion2market").joinpath("web/index.html").read_bytes()
            html = html.replace(b"__VERSION__", __version__.encode())
            return self._send(200, html, "text/html; charset=utf-8")
        with _open() as store:
            if path == "/api/items":
                return self._json(item_rows(store, server_id=server_id))
            if path == "/api/deals":
                sid = server_id or default_server(store)
                series = load_series(store, sid)
                rows = item_rows(store, server_id=sid, series=series)
                fee = sell_fee_pct(store)
                return self._json({**rows, "items": deals(rows["items"], fee, lang), "fee_pct": fee,
                                   "morphs": morph_table(rows["items"], fee),
                                   "weekdays": pattern_summary(weekday_pattern(series, rows["now"]), lang),
                                   "rules": {"min_discount": DEAL_MIN_DISCOUNT * 100, "min_drop": -DEAL_MIN_DROP,
                                             "min_listings": DEAL_MIN_LISTINGS, "min_days": DEAL_MIN_DAYS}})
            if path == "/api/settings":
                return self._json({"exclude": get_exclude(store)})
            if path == "/api/inventory":
                return self._json(inventory_view(store, server_id, lang))
            if path == "/api/crafting":
                return self._json(crafting_view(store, server_id, lang))
            if path == "/api/servers":
                return self._json({"servers": store.servers(), "home": store.home_server(),
                                   "sync": sync_status(store), "npcap": npcap_status(store),
                                   "update": updates.status()})
            if path.startswith("/api/item/") and path[10:].isdigit():
                return self._json(item_detail(store, path[10:], server_id, lang))
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")

    def do_POST(self):
        # A JSON content type can't be sent cross-site without a CORS preflight, which we never allow.
        if not self._host_ok() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(HTTPStatus.FORBIDDEN, b"forbidden", "text/plain")
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10_000)) or b"{}")
            key = str(body.get("item_key", ""))
        except (ValueError, AttributeError):
            return self._json({"error": "bad request"}, 400)
        if self.path == "/api/settings":
            exclude = clean_exclude(body.get("exclude"))
            with _open() as store:
                store.set_meta(EXCLUDE_KEY, json.dumps(exclude, ensure_ascii=False))
            return self._json({"exclude": exclude})
        if self.path == "/api/server-name":
            sid, name = str(body.get("server_id", "")), str(body.get("name") or "").strip()[:40]
            if not sid.isdigit() or not name:
                return self._json({"error": "server_id/name"}, 400)
            with _open() as store:
                store.set_server_name(int(sid), name)
            return self._json({"ok": True})
        if self.path == "/api/sync":
            if not isinstance(body.get("enabled"), bool):
                return self._json({"error": "enabled"}, 400)
            from . import sync
            with _open() as store:
                sync.set_enabled(store, body["enabled"])
                return self._json(sync_status(store))
        if not key.isdigit():
            return self._json({"error": "item_key"}, 400)
        with _open() as store:
            if self.path == "/api/name":
                name = str(body.get("name") or "").strip()[:80]
                if name:
                    store.set_name(key, name)
                else:
                    store.clear_name(key)            # back to the official name, if any
                return self._json({"ok": True, "name": store.name(key)})
            if self.path == "/api/watch":
                target = body.get("target")
                if body.get("watch") is False:
                    store.unwatch(key)
                else:
                    store.watch(key, float(target) if target not in (None, "") else None, time.time())
                return self._json({"ok": True})
        self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain")


class _open:
    def __enter__(self) -> Store:
        self.store = Store(db_path())
        return self.store

    def __exit__(self, *exc) -> None:
        self.store.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aion 2 market fiyat arayüzü (yerel web sayfası).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="tarayıcıyı otomatik açma")
    args = ap.parse_args(argv)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Arayüz: {url}  — durdurmak için Ctrl+C")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
