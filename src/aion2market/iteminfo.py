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

from .store import Store, item_detail

API = "https://tw.ncsoft.com/aion2/api/gameconst/item"
DELAY = 0.5                      # seconds between requests
RETRY_UNKNOWN_AFTER = 6 * 3600   # look again at keys the API didn't know (added later, or a bad answer)
TOOLTIP_TIMEOUT = 5.0            # a tooltip waits for this lookup, so it gives up sooner than the background one
TOOLTIP_RETRY_AFTER = 600.0      # a key whose tooltip lookup failed isn't asked again on every hover
_tooltip_failed: dict[str, float] = {}       # item_key -> when its on-demand lookup failed or found nothing


def fetch(item_key: str, lang: str = "en", timeout: float = 15) -> dict | None:
    """Official data for one item, or None if the API doesn't know it (it answers with id 0)."""
    query = urllib.parse.urlencode({"id": item_key, "enchantLevel": 0, "lang": lang})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "aion2market (item names)",
                                                           "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def tooltip(store: Store, item_key: str, fetcher=None, now: float | None = None) -> dict:
    """Everything known about one item, for its tooltip. Items stored before details were kept (or never
    looked up) are fetched once, with a short timeout; ``"detail": False`` means that didn't work and
    only the basic fields are known. ``fetcher`` is ``fetch`` with the short timeout unless given."""
    now = time.time() if now is None else now
    info = store.item_info_for(item_key)
    failed = _tooltip_failed.get(item_key)
    if not (info and info["detail"]) and (failed is None or now - failed >= TOOLTIP_RETRY_AFTER):
        try:
            data = fetcher(item_key) if fetcher else fetch(item_key, timeout=TOOLTIP_TIMEOUT)
        except (OSError, ValueError, http.client.HTTPException):
            data = None
        if not data:
            # Nothing is written: a failed lookup must not turn a known item into an unknown one.
            _tooltip_failed[item_key] = now
        else:
            _tooltip_failed.pop(item_key, None)
            if info and info["source"] == "nc":
                store.set_item_detail(item_key, data)
            else:
                store.set_item_info(item_key, data, now)
            info = store.item_info_for(item_key)
    info = info or {}
    detail = info.get("detail")
    return {"item_key": item_key, "name": store.name(item_key), "official_name": info.get("name"),
            "grade_name": info.get("grade_name"), "category": info.get("category"), "type": info.get("type"),
            "icon": info.get("icon"), "detail": bool(detail), **(detail or item_detail({}))}


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
