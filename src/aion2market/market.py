"""Turn decrypted qos-api.g.nc.com market exchanges into stored observations."""
from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime

from .http1 import HttpMessage
from .store import Store

MARKET_HOST = "qos-api.g.nc.com"
SALES_PREFIX = "/trade/v1.0/sales/"
ME_PREFIX = "/trade/v1.0/me/"            # the player's own sales/earnings: stored raw for later use
SUMMARY_PATH = "/trade/v1.0/sales/valid/summary/min_unit_price"
PAGES_PATH = "/trade/v1.0/sales/valid/pages"
POLICIES_PATH = "/trade/v1.0/policies"
DEFAULT_FEE_PCT = 12.0                   # policies list 10 % + 2 %; used until the game sends its own


def sell_fee_pct(store: Store) -> float:
    """Total market fee taken from a sale, in percent (from the latest policies the game loaded)."""
    try:
        return float(store.get_meta("market.fee_pct", str(DEFAULT_FEE_PCT)))
    except ValueError:
        return DEFAULT_FEE_PCT


def server_time(loaded: str | None) -> float | None:
    try:
        return datetime.fromisoformat(loaded).timestamp() if loaded else None
    except ValueError:
        return None


def fmt_price(v: float) -> str:
    return f"{v:,.0f}".replace(",", ".")


def handle_exchange(store: Store, request: HttpMessage, response: HttpMessage,
                    now: float | None = None, observed: dict[str, float] | None = None) -> list[str]:
    """Store one request/response pair; returns human-readable log lines (empty if ignored).

    If given, ``observed`` is filled with the lowest unit price seen per item key."""
    if observed is None:
        observed = {}
    path = request.path
    if path == POLICIES_PATH:
        return _policies(store, response)
    if not path.startswith((SALES_PREFIX, ME_PREFIX)):
        return []
    try:
        req = json.loads(request.body or b"{}")
        resp = json.loads(response.body or b"{}")
    except ValueError:
        return []
    ts = server_time(resp.get("loaded")) or now or time.time()
    if not store.add_response(ts, path, request.body.decode("utf-8", "replace"), response.status,
                              response.body.decode("utf-8", "replace")):
        return []                                           # already stored (replay)
    if response.status != 200:
        return []
    server_id = int(req.get("game_server_id") or 0)
    stamp = datetime.fromtimestamp(ts).strftime("%H:%M:%S")

    if path == SUMMARY_PATH:
        rows = [(i["game_item_key"], float(i["min_unit_price"]), int(i["sale_count"])) for i in resp.get("list", [])]
        store.add_snapshots(ts, server_id, rows)
        observed.update({key: price for key, price, _ in rows})
        if len(rows) == 1:
            key, price, count = rows[0]
            return [f"{stamp} {_label(store, key)}: en düşük birim fiyat {fmt_price(price)} ({count} ilan)"]
        return [f"{stamp} {len(rows)} item'ın en düşük fiyatı kaydedildi"]

    if path == PAGES_PATH:
        sales = resp.get("sales", [])
        store.add_listings(ts, server_id, sales)
        by_item = defaultdict(list)
        for s in sales:
            by_item[s["game_item_key"]].append(s)
        lines = []
        for key, items in by_item.items():
            single = [int(s["sale_price"]) for s in items if s["game_item_quantity"] == "1"]
            cheapest = min(float(s["unit_price"]) for s in items)
            observed[key] = cheapest
            extra = f", 1 adet en ucuz {fmt_price(min(single))}" if single else ""
            lines.append(f"{stamp} {_label(store, key)}: {len(items)} ilan, birim en ucuz {fmt_price(cheapest)}{extra}")
        return lines
    return []


def _policies(store: Store, response: HttpMessage) -> list[str]:
    try:
        fees = json.loads(response.body or b"{}").get("fee") or []
        total = sum(float(f["fee_rate"]) for f in fees)
    except (ValueError, KeyError, TypeError, AttributeError):
        return []
    if 0 < total < 100 and str(total) != store.get_meta("market.fee_pct"):
        store.set_meta("market.fee_pct", str(total))
        return [f"Market kesintisi güncellendi: %{total:g}"]
    return []


def _label(store: Store, key: str) -> str:
    name = store.name(key)
    return f"{name} ({key})" if name else key
