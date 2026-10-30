"""Import market prices for one server from aion2.exchange, a site that tracks every server.

Uses the API shape seen in a community script:

    GET https://aion2.exchange/api/items?server=<id>&keys=<k1,k2,...>&limit=100
        -> {"items": [{"item_key", "price", "listings", "change_pct", "captured_at"}, ...]}

Rows are stored as origin 'exchange' next to your own ('local') and shared ones,
are never re-uploaded to the shared store, and fresh ones on your own server can
trigger watchlist alerts. Requests are few and identify this tool honestly; be
gentle with someone else's service.

    python -m aion2market.exchange setup 12306      # market server id, as in aion2.exchange URLs (?server=)
    python -m aion2market.exchange now
    python -m aion2market.exchange history           # one-time: 30 days of 6-hour price ranges per item
    python -m aion2market.exchange disable
"""
from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Callable

from . import alerts
from .store import Store

API = "https://aion2.exchange/api"
USER_AGENT = "aion2market personal price tracker (single user)"
BATCH = 100                  # item keys per request
DELAY = 2.0                  # seconds between requests
INTERVAL = 30 * 60           # service poll interval; the site itself samples about once an hour
ALERT_WINDOW = 30 * 60


class ExchangeError(Exception):
    pass


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ExchangeError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
        raise ExchangeError(str(getattr(e, "reason", e))) from None


def _ts(value) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_items(payload: dict) -> list[tuple[str, float, int, float]]:
    """(item_key, unit price, listings, captured ts) for usable rows; anything odd is skipped."""
    rows = []
    for entry in payload.get("items") or []:
        try:
            key = str(int(entry["item_key"]))
            price = float(entry.get("price") or 0)
            listings = int(entry.get("listings") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        ts = _ts(entry.get("captured_at"))
        if price > 0 and ts is not None:
            rows.append((key, price, listings, ts))
    return rows


# aion2.exchange category -> NC's label for the same items, so the category filter doesn't split them
# (e.g. NC's "Artwork: Fire Temple" is in "Pantheon Decor" while aion2.exchange calls it "Artwork").
CATEGORY_TO_NC = {"Artwork": "Pantheon Decor", "Crafting materials": "Crafting Material"}


def parse_names(payload: dict) -> list[tuple[str, str | None, str | None]]:
    """(item_key, name, category) where the response has either."""
    out = []
    for entry in payload.get("items") or []:
        try:
            key = str(int(entry["item_key"]))
        except (KeyError, TypeError, ValueError):
            continue
        name = entry.get("name") if isinstance(entry.get("name"), str) and entry["name"].strip() else None
        cat = entry.get("category")
        cat = cat.get("name") if isinstance(cat, dict) else None
        cat = CATEGORY_TO_NC.get(cat, cat) if isinstance(cat, str) and cat.strip() else None
        if name or cat:
            out.append((key, name and name.strip()[:120], cat and cat[:60]))
    return out


def fetch_prices(server_id: int, keys: list[str], fetcher: Callable[[str], dict] = http_json,
                 delay: float = DELAY) -> tuple[list[tuple[str, float, int, float]], list[tuple]]:
    """(price rows, names) for the given keys, BATCH keys per request."""
    rows, names = [], []
    for i in range(0, len(keys), BATCH):
        if i:
            time.sleep(delay)
        query = urllib.parse.urlencode({"server": server_id, "keys": ",".join(keys[i:i + BATCH]), "limit": BATCH})
        payload = fetcher(f"{API}/items?{query}")
        rows += parse_items(payload)
        names += parse_names(payload)
    return rows, names


def _span(bucket) -> float | None:
    units = {"m": 60, "h": 3600, "d": 86400}
    try:
        return float(str(bucket)[:-1]) * units[str(bucket)[-1]]
    except (KeyError, ValueError, IndexError):
        return None


def parse_history(payload: dict) -> list[tuple]:
    """Buckets from /items/<key>/prices: (start ts, span, low, high, avg, close, listings, samples)."""
    span = _span(payload.get("bucket"))
    if span is None:
        return []
    rows = []
    for p in payload.get("points") or []:
        ts = _ts(p.get("ts"))
        try:
            low, high, close = float(p["low"]), float(p["high"]), float(p["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if ts is None or not 0 < low <= high or close <= 0:
            continue
        avg = p.get("avg")
        rows.append((ts, span, low, high, float(avg) if avg is not None else None, close,
                     p.get("listings"), p.get("samples")))
    return rows


def store_history(store: Store, server_id: int, key: str, rows: list[tuple], range_end: float | None) -> int:
    """Keep the buckets and add each finished bucket's closing price as a price point at the bucket's
    end, so the week/month changes and charts work right away. The unfinished last bucket gets no
    point: its time would be the request time (spread over the whole fill), and the current price
    comes from the regular polling anyway."""
    store.add_ranges(server_id, key, rows)
    points = [(ts + span, server_id, key, close, int(listings or 0))
              for ts, span, _, _, _, close, listings, _ in rows
              if range_end is None or ts + span <= range_end]
    cur = store.db.executemany(
        "INSERT OR IGNORE INTO price_snapshots (ts, server_id, item_key, min_unit_price, sale_count, origin) "
        "VALUES (?, ?, ?, ?, ?, 'exchange')", points)
    store.db.commit()
    return cur.rowcount


def backfill(store: Store, server_id: int, range_: str = "30d", fetcher: Callable[[str], dict] = http_json,
             delay: float = DELAY, progress=None) -> tuple[int, int, int]:
    """Load price history once per item; later prices come from the regular polling.
    Returns (items loaded, skipped as already loaded, errors)."""
    done_key = f"exchange.history.{server_id}.{range_}"
    loaded = set(json.loads(store.get_meta(done_key, "[]")))
    keys = [k for k in tracked_keys(store) if k not in loaded]
    skipped = len(tracked_keys(store)) - len(keys)
    done = errors = 0
    for i, key in enumerate(keys):
        if i:
            time.sleep(delay)
        query = urllib.parse.urlencode({"server": server_id, "range": range_})
        try:
            payload = fetcher(f"{API}/items/{key}/prices?{query}")
        except ExchangeError as e:
            errors += 1
            if progress:
                progress(i + 1, len(keys), key, f"hata: {e}")
            if errors >= 5 and done == 0:
                break                                  # the source is down or refusing; stop early
            continue
        rows = parse_history(payload)
        store_history(store, server_id, key, rows, _ts(payload.get("range_end")))
        loaded.add(key)
        store.set_meta(done_key, json.dumps(sorted(loaded)))      # an interrupted run resumes here
        done += 1
        if progress:
            progress(i + 1, len(keys), key, f"{len(rows)} dilim")
    return done, skipped, errors


def tracked_keys(store: Store) -> list[str]:
    """Every item seen in any market so far, the watchlist, and all crafting-chain items."""
    from .recipes import all_keys
    rows = store.db.execute("SELECT item_key FROM price_snapshots UNION SELECT item_key FROM watchlist").fetchall()
    return sorted({r[0] for r in rows} | all_keys())


def import_once(store: Store, fetcher: Callable[[str], dict] = http_json, notifier=None,
                now: float | None = None, delay: float = DELAY) -> list[str]:
    now = now or time.time()
    server = store.get_meta("exchange.server")
    if not server:
        return ["aion2.exchange ayarlı değil: python -m aion2market.exchange setup <sunucu-id>"]
    server_id = int(server)
    keys = tracked_keys(store)
    if not keys:
        return []
    try:
        rows, names = fetch_prices(server_id, keys, fetcher, delay)
    except ExchangeError as e:
        store.set_meta("exchange.last_error", str(e)[:200])
        return [f"aion2.exchange'den alınamadı: {e}"]
    new = []
    for key, price, listings, ts in rows:
        cur = store.db.execute(
            "INSERT OR IGNORE INTO price_snapshots (ts, server_id, item_key, min_unit_price, sale_count, origin) "
            "VALUES (?, ?, ?, ?, ?, 'exchange')", (ts, server_id, key, price, listings))
        if cur.rowcount:
            new.append((key, price, ts))
    store.db.commit()
    store.set_exchange_names(names, now)            # only shown for items NC's data doesn't know
    store.set_meta("exchange.last_ok", str(now))
    store.db.execute("DELETE FROM meta WHERE key = 'exchange.last_error'")
    store.db.commit()
    lines = [f"aion2.exchange: {len(rows)} fiyat okundu, {len(new)} yeni (sunucu {server_id})"] if new else []
    # Only fresh prices for this computer's own market may raise alerts.
    if server_id == store.home_server() or store.home_server() is None:
        fresh = {k: p for k, p, ts in new if ts >= now - ALERT_WINDOW}
        for alert in alerts.check(store, fresh, now):
            lines.append(f"!!! BİLDİRİM (aion2.exchange) {alert.text()}")
            if notifier is not None:
                lines += [f"    gönderilemedi: {e}" for e in notifier(alert)]
    return lines


def main(argv: list[str] | None = None) -> int:
    from .service import DEFAULT_DB

    ap = argparse.ArgumentParser(description="aion2.exchange'den tek bir sunucunun fiyatlarını alır.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup", help="hangi sunucunun fiyatları alınsın")
    p.add_argument("server_id", type=int, help="aion2.exchange adresindeki ?server= değeri, ör. 12306")
    sub.add_parser("now", help="hemen al")
    p = sub.add_parser("history", help="geçmiş fiyat aralıklarını bir kez doldur (item başına bir istek)")
    p.add_argument("--range", default="30d", help="ör. 7d, 30d (varsayılan 30d)")
    sub.add_parser("disable", help="kapat")
    args = ap.parse_args(argv)
    store = Store(args.db)
    try:
        if args.cmd == "history":
            server = store.get_meta("exchange.server")
            if not server:
                print("Önce: python -m aion2market.exchange setup <sunucu-id>")
                return 1
            n = len(tracked_keys(store))
            print(f"Sunucu {server}, {n} item, istekler arası {DELAY:g} sn (en fazla ~{n * DELAY / 60:.0f} dk)")

            def show(i, total, key, what):
                print(f"[{i}/{total}] {key}  {what}", flush=True)
            done, skipped, errors = backfill(store, int(server), args.range, progress=show)
            print(f"Bitti: {done} item yüklendi, {skipped} item zaten yüklüydü, {errors} hata.")
            return 0
        if args.cmd == "setup":
            store.set_meta("exchange.server", str(args.server_id))
            print(f"Sunucu {args.server_id} kaydedildi. Servis çalışırken {INTERVAL // 60} dakikada bir alınır; "
                  "şimdi denemek için: exchange now")
        elif args.cmd == "disable":
            store.db.execute("DELETE FROM meta WHERE key LIKE 'exchange.%'")
            store.db.commit()
            print("aion2.exchange kapatıldı.")
        else:
            for line in import_once(store) or ["Yeni fiyat yok."]:
                print(line)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
