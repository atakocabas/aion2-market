"""MCP server over the market database written by ``aion2market.service``.

Read-mostly: it only queries data/market.db and edits the user's own item names
and watchlist there. It never talks to the game or its servers.

    python -m aion2market.mcp_server          # stdio transport

The database path can be overridden with the AION2_DB environment variable.
"""
from __future__ import annotations

import os
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .store import Store

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INSTRUCTIONS = """\
Aion 2 market prices recorded passively from the user's own game client.
Prices only update when the user opens the in-game market (or searches an item)
while `python -m aion2market.service run` is running, so always mention how old
a price is (`as_of`, `age_minutes`). Prices are in Kinah. Item names are not sent
by the game; they come from the user via `name_item`. An item can always be
referred to by its numeric game_item_key."""

server = MCPServer("aion2-market", instructions=INSTRUCTIONS)


def db_path() -> Path:
    return Path(os.environ.get("AION2_DB") or PROJECT_ROOT / "data" / "market.db")


def _open() -> closing[Store]:
    return closing(Store(db_path()))


def _when(ts: float) -> dict:
    return {"as_of": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "age_minutes": round((time.time() - ts) / 60, 1)}


def _num(v: float | None):
    return None if v is None else (int(v) if float(v).is_integer() else v)


def _resolve(store: Store, item: str) -> str | dict:
    """item_key, or an error dict."""
    item = item.strip()
    keys = store.resolve(item)
    if not keys:
        return {"error": f"No item named '{item}'. Use the numeric game_item_key, or name it with name_item.",
                      "known_items": [n for _, n in store.named_items()]}
    exact = [k for k in keys if (store.name(k) or "").lower() == item.lower()]
    if len(keys) > 1 and len(exact) != 1:
        return {"error": f"'{item}' matches several items; be more specific.",
                      "matches": [{"item_key": k, "name": store.name(k)} for k in keys]}
    return (exact or keys)[0]


def _item(store: Store, key: str) -> dict:
    return {"item_key": key, "name": store.name(key)}


def _server(store: Store, server_id: int | None) -> int | None:
    """Requested market server, else this computer's own (prices differ per server)."""
    return server_id or store.home_server()


def _price(store: Store, key: str, server_id: int | None = None) -> dict:
    server_id = _server(store, server_id)
    out = {**_item(store, key), "server_id": server_id}
    snap = store.latest_snapshot(key, server_id)
    if snap:
        ts, price, count = snap
        out["summary"] = {"min_unit_price": _num(price), "listing_count": count, **_when(ts)}
    ts, rows = store.latest_listings(key, server_id)
    if rows:
        single = [sale for qty, sale, _ in rows if qty == 1]
        out["last_search"] = {"listing_count": len(rows), "cheapest_unit_price": _num(rows[0][2]),
                              "cheapest_single_unit": min(single) if single else None, **_when(ts)}
    if not snap and not rows:
        out["error"] = "No price recorded yet. Open this item in the in-game market while the service runs."
    return out


@server.tool()
def get_price(item: str, server_id: int | None = None) -> dict:
    """Latest known market price of an item (name or game_item_key).

    `summary` is the market-wide minimum unit price (also covers stacks);
    `last_search` comes from the most recent time the user searched this item and
    includes the cheapest single-unit listing. `server_id` defaults to the user's
    own market server; see list_servers."""
    with _open() as store:
        key = _resolve(store, item)
        return key if isinstance(key, dict) else _price(store, key, server_id)


@server.tool()
def list_servers() -> dict:
    """Market servers with recorded prices (own and shared), newest data first."""
    with _open() as store:
        return {"home_server": store.home_server(),
                "servers": [{**s, "latest": datetime.fromtimestamp(s["latest"]).strftime("%Y-%m-%d %H:%M")}
                            for s in store.servers()]}


@server.tool()
def price_history(item: str, days: float = 7, server_id: int | None = None) -> dict:
    """Recorded price points of an item over the last `days` days, oldest first."""
    with _open() as store:
        key = _resolve(store, item)
        if isinstance(key, dict):
            return key
        server_id = _server(store, server_id)
        since = time.time() - days * 86400
        fmt = "%Y-%m-%d %H:%M"
        # Opening the market and then the item yields the same value seconds apart; keep changes only.
        summary, last = [], None
        for ts, p, c in store.snapshot_history(key, since, server_id):
            if (p, c) != last:
                summary.append({"time": datetime.fromtimestamp(ts).strftime(fmt), "min_unit_price": _num(p),
                                "listing_count": c})
                last = (p, c)
        return {
            **_item(store, key), "server_id": server_id,
            "summary": summary,
            "searches": [{"time": datetime.fromtimestamp(ts).strftime(fmt), "listing_count": n,
                          "cheapest_unit_price": _num(u), "cheapest_single_unit": s}
                         for ts, n, u, s in store.listing_history(key, since, server_id)],
        }


@server.tool()
def cheapest_listings(item: str, limit: int = 10, quantity: int | None = None,
                      server_id: int | None = None) -> dict:
    """Cheapest listings (by unit price) from the most recent search of an item.

    `quantity` keeps only listings of exactly that stack size (e.g. 1)."""
    with _open() as store:
        key = _resolve(store, item)
        if isinstance(key, dict):
            return key
        server_id = _server(store, server_id)
        ts, rows = store.latest_listings(key, server_id)
        if not rows:
            return {**_item(store, key), "error": "This item was never searched while the service was running."}
        if quantity is not None:
            rows = [r for r in rows if r[0] == quantity]
        return {**_item(store, key), "server_id": server_id, **_when(ts),
                "listings": [{"quantity": q, "total_price": s, "unit_price": _num(u)}
                             for q, s, u in rows[:max(1, min(limit, 100))]]}


@server.tool()
def watch_item(item: str, target_price: float | None = None) -> dict:
    """Add an item to the watchlist, optionally with a target unit price.

    While the service runs, a notification is sent when an observed unit price
    is at or below the target, and again only if it drops further. Without a
    target, it fires at 20 % under the item's 7-day average. Setting a new
    target starts over."""
    with _open() as store:
        key = _resolve(store, item)
        if isinstance(key, dict):
            return key
        store.watch(key, target_price, time.time())
        return {"watching": _item(store, key), "target_price": _num(target_price)}


@server.tool()
def unwatch_item(item: str) -> dict:
    """Remove an item from the watchlist."""
    with _open() as store:
        key = _resolve(store, item)
        if isinstance(key, dict):
            return key
        return {**_item(store, key), "removed": store.unwatch(key)}


@server.tool()
def list_watchlist() -> dict:
    """Watched items with their latest prices and whether they are at or below target."""
    with _open() as store:
        items = []
        for key, target in store.watchlist():
            p = _price(store, key)
            p["target_price"] = _num(target)
            current = p.get("summary", {}).get("min_unit_price")
            p["at_or_below_target"] = None if target is None or current is None else current <= target
            items.append(p)
        return {"items": items}


@server.tool()
def name_item(item_key: str, name: str) -> dict:
    """Give a game_item_key a human-readable name (the game does not send names)."""
    if not item_key.strip().isdigit() or not name.strip():
        return {"error": "item_key must be the numeric game_item_key and name must not be empty."}
    with _open() as store:
        store.set_name(item_key.strip(), name.strip())
        return _item(store, item_key.strip())


@server.tool()
def recent_searches(limit: int = 10) -> dict:
    """Items the user searched most recently in the market, to find a game_item_key to name."""
    with _open() as store:
        rows = store.db.execute(
            "SELECT item_key, MAX(ts) FROM listings GROUP BY item_key ORDER BY MAX(ts) DESC LIMIT ?",
            (max(1, min(limit, 50)),)).fetchall()
        return {"items": [{**_item(store, k), **_when(ts)} for k, ts in rows]}


@server.tool()
def recent_alerts(limit: int = 10) -> dict:
    """Price notifications sent for watched items, newest first."""
    with _open() as store:
        return {"alerts": [{**_item(store, k), "price": _num(p), "target_price": _num(t),
                            "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")}
                           for ts, k, p, t in store.recent_alerts(max(1, min(limit, 100)))]}


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
