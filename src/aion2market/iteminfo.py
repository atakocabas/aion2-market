"""Fill in item names, grades, categories and icons from NCSOFT's public item data.

This is the only part of the project that contacts anything: plain GET requests
to NC's public website API, one item at a time, slowly. It never touches the
game or the game account.

    python -m aion2market.iteminfo           # look up every item seen so far
"""
from __future__ import annotations

import argparse
import http.client
import json
import time
import urllib.parse
import urllib.request

from .store import Store

API = "https://tw.ncsoft.com/aion2/api/gameconst/item"
DELAY = 0.5                      # seconds between requests
RETRY_UNKNOWN_AFTER = 6 * 3600   # look again at keys the API didn't know (added later, or a bad answer)


def fetch(item_key: str, lang: str = "en") -> dict | None:
    """Official data for one item, or None if the API doesn't know it (it answers with id 0)."""
    query = urllib.parse.urlencode({"id": item_key, "enchantLevel": 0, "lang": lang})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "aion2market (item names)",
                                                           "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if str(data.get("id")) != item_key or not data.get("name"):
        return None
    return data


def fill_missing(store: Store, delay: float = DELAY, limit: int | None = None, progress=None,
                 fetcher=fetch, stop=lambda: False) -> tuple[int, int, int]:
    """Look up items without official data. Returns (found, unknown, errors)."""
    keys = store.keys_missing_info(time.time() - RETRY_UNKNOWN_AFTER)[:limit]
    found = unknown = errors = 0
    last_error = None
    for i, key in enumerate(keys):
        if stop():
            break
        try:
            info = fetcher(key)
        except (OSError, ValueError, http.client.HTTPException) as e:
            errors += 1
            last_error = f"{type(e).__name__}: {e}"
            if progress:
                progress(i + 1, len(keys), key, f"hata: {e}")
            if errors >= 5 and found + unknown == 0:
                break                 # source unreachable; try again later
            continue
        finally:
            if i + 1 < len(keys):
                time.sleep(delay)
        store.set_item_info(key, info, time.time())
        if info:
            found += 1
        else:
            unknown += 1
        if progress:
            progress(i + 1, len(keys), key, info["name"] if info else "(resmi veride yok)")
    if found or unknown:          # the source answered: a few failed keys are not worth showing
        store.set_meta("iteminfo.last_ok", str(time.time()))
        store.db.execute("DELETE FROM meta WHERE key = 'iteminfo.last_error'")
        store.db.commit()
    elif last_error:
        store.set_meta("iteminfo.last_error", last_error[:200])
    return found, unknown, errors


def main(argv: list[str] | None = None) -> int:
    from .service import DEFAULT_DB

    ap = argparse.ArgumentParser(description="Item adlarını NCSOFT'un resmi item verisinden doldurur.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--limit", type=int, help="en fazla bu kadar item sorgula")
    args = ap.parse_args(argv)
    store = Store(args.db)
    try:
        def show(i, n, key, what):
            print(f"[{i}/{n}] {key}  {what}", flush=True)
        found, unknown, errors = fill_missing(store, limit=args.limit, progress=show)
        print(f"Bitti: {found} ad bulundu, {unknown} item resmi veride yok, {errors} hata.")
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
