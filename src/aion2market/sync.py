"""Share market observations with other users through the Cloudflare store (cloud/).

Uploads only what this computer's own game client saw (origin 'local') and
downloads everyone's rows as origin 'shared'. What is sent: server id, item key,
time, prices, listing counts and listing ids/prices, plus the official item
names/grades/icons looked up from NC's public API (iteminfo.py), so users whose
network can't reach that API still get names. Nothing about the character,
account or session.

The store's address is built in (DEFAULT_URL); on first use the app asks the
store for its own key. Sharing is on by default and can be switched off in the
window or with `disable`.

    python -m aion2market.sync now           # one sync (the service also syncs every minute)
    python -m aion2market.sync status
    python -m aion2market.sync disable | enable
    python -m aion2market.sync setup https://<worker>.workers.dev [a2m_<key>]   # another store / an invited key

    # store owner only
    python -m aion2market.sync admin --url ... --admin-token ... create-key "Ali"
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import time
import urllib.error
import urllib.request

from . import alerts
from .store import Store

# The shared store every installation uses unless told otherwise. Fill in after `wrangler deploy`
# (cloud/README.md); empty means no built-in store.
DEFAULT_URL = "https://aion2-market.aion2-market-cloud.workers.dev"

UPLOAD_SNAPSHOTS = 5000
UPLOAD_LISTINGS = 2000
UPLOAD_ITEMS = 2000
ALERT_WINDOW = 30 * 60     # only fresh shared prices may trigger alerts
REGISTER_RETRY = 10 * 60   # after a failed self-registration, wait this long before asking again


class ShareError(Exception):
    pass


class ShareClient:
    def __init__(self, url: str, key: str, timeout: float = 30):
        self.url = url.rstrip("/")
        self.key = key
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
            "User-Agent": "aion2market-sync"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error", "")
            except ValueError:
                msg = ""
            raise ShareError(f"HTTP {e.code} {msg}".strip()) from None
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as e:
            raise ShareError(str(getattr(e, "reason", e))) from None


def share_url(store: Store) -> str | None:
    return os.environ.get("AION2_SHARE_URL") or store.get_meta("sync.url") or DEFAULT_URL or None


def enabled(store: Store) -> bool:
    return store.get_meta("sync.enabled", "1") == "1"


def set_enabled(store: Store, on: bool) -> None:
    store.set_meta("sync.enabled", "1" if on else "0")
    if not on:
        store.db.execute("DELETE FROM meta WHERE key = 'sync.last_error'")
        store.db.commit()


def client_from(store: Store) -> ShareClient | None:
    """A client when sharing is on and this computer already has a key."""
    url = share_url(store)
    key = os.environ.get("AION2_SHARE_KEY") or store.get_meta("sync.key")
    return ShareClient(url, key) if url and key and enabled(store) else None


def register(store: Store, url: str, now: float | None = None) -> ShareClient:
    """Ask the store for this computer's own key and remember it."""
    now = now or time.time()
    try:
        r = ShareClient(url, "").request("POST", "/v1/register", {})
    except ShareError:
        store.set_meta("sync.register_after", str(now + REGISTER_RETRY))
        raise
    store.set_meta("sync.url", url.rstrip("/"))
    store.set_meta("sync.key", r["key"])
    return ShareClient(url, r["key"])


def ensure_client(store: Store, now: float | None = None) -> ShareClient | None:
    """client_from, registering first if sharing is on but there is no key yet (retried every few minutes)."""
    client = client_from(store)
    url = share_url(store)
    if client is not None or not url or not enabled(store):
        return client
    now = now or time.time()
    if now < float(store.get_meta("sync.register_after", "0")):
        return None
    try:
        return register(store, url, now)
    except ShareError as e:
        store.set_meta("sync.last_error", f"kayıt: {e}"[:200])
        return None


def upload_pending(store: Store, client: ShareClient) -> tuple[int, int]:
    """Send local rows not uploaded yet; cursors are SQLite rowids so nothing is sent twice."""
    sent_snaps = sent_lists = 0
    while True:
        cursor = int(store.get_meta("sync.up.snapshots", "0"))
        rows = store.db.execute(
            "SELECT rowid, server_id, item_key, ts, min_unit_price, sale_count FROM price_snapshots "
            "WHERE origin = 'local' AND rowid > ? ORDER BY rowid LIMIT ?", (cursor, UPLOAD_SNAPSHOTS)).fetchall()
        if not rows:
            break
        client.request("POST", "/v1/upload", {"snapshots": [[s, k, t, p, c] for _, s, k, t, p, c in rows]})
        store.set_meta("sync.up.snapshots", str(rows[-1][0]))
        sent_snaps += len(rows)
    while True:
        cursor = int(store.get_meta("sync.up.listings", "0"))
        rows = store.db.execute(
            "SELECT rowid, server_id, item_key, ts, sale_id, quantity, sale_price, unit_price, effective_from, "
            "effective_to, grade_id, category_id FROM listings WHERE origin = 'local' AND rowid > ? "
            "ORDER BY rowid LIMIT ?", (cursor, UPLOAD_LISTINGS)).fetchall()
        if not rows:
            break
        client.request("POST", "/v1/upload", {"listings": [list(r[1:]) for r in rows]})
        store.set_meta("sync.up.listings", str(rows[-1][0]))
        sent_lists += len(rows)
    return sent_snaps, sent_lists


def download_new(store: Store, client: ShareClient) -> tuple[list[tuple[int, str, float, float]], int]:
    """Fetch rows other users uploaded. Returns (new snapshot rows (server, key, ts, price), new listings)."""
    new_snaps: list[tuple[int, str, float, float]] = []
    while True:
        cursor = int(store.get_meta("sync.down.snapshots", "0"))
        page = client.request("GET", f"/v1/snapshots?since={cursor}")
        for _, server_id, key, ts, price, count in page["rows"]:
            cur = store.db.execute(
                "INSERT OR IGNORE INTO price_snapshots (ts, server_id, item_key, min_unit_price, sale_count, origin) "
                "VALUES (?, ?, ?, ?, ?, 'shared')", (ts, server_id, key, price, count))
            if cur.rowcount:
                new_snaps.append((server_id, key, ts, price))
        store.db.commit()
        store.set_meta("sync.down.snapshots", str(page["next"]))
        if not page["more"]:
            break
    new_lists = 0
    while True:
        cursor = int(store.get_meta("sync.down.listings", "0"))
        page = client.request("GET", f"/v1/listings?since={cursor}")
        cur = store.db.executemany(
            "INSERT OR IGNORE INTO listings (server_id, item_key, ts, sale_id, quantity, sale_price, unit_price, "
            "effective_from, effective_to, grade_id, category_id, origin) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'shared')",
            [r[1:] for r in page["rows"]])
        new_lists += max(cur.rowcount, 0)
        store.db.commit()
        store.set_meta("sync.down.listings", str(page["next"]))
        if not page["more"]:
            break
    known = {s["server_id"] for s in store.servers() if s["name"]}
    for s in client.request("GET", "/v1/servers")["servers"]:
        if s["server_id"] not in known:              # a name given locally wins
            store.set_server_name(s["server_id"], s["name"])
    return new_snaps, new_lists


_ITEM_COLS = "item_key, name, grade, grade_name, category, type, icon"


def upload_items(store: Store, client: ShareClient) -> int:
    """Send official item data this computer looked up, so computers that can't reach NC get names too."""
    sent = 0
    while True:
        cursor = int(store.get_meta("sync.up.items", "0"))
        rows = store.db.execute(
            f"SELECT rowid, {_ITEM_COLS} FROM item_info WHERE found = 1 AND name IS NOT NULL AND rowid > ? "
            "ORDER BY rowid LIMIT ?", (cursor, UPLOAD_ITEMS)).fetchall()
        if not rows:
            return sent
        client.request("POST", "/v1/upload", {"items": [list(r[1:]) for r in rows]})
        store.set_meta("sync.up.items", str(rows[-1][0]))
        sent += len(rows)


def download_items(store: Store, client: ShareClient, now: float) -> int:
    """Official item data other users looked up; fills items this computer has no data for."""
    new = 0
    while True:
        cursor = int(store.get_meta("sync.down.items", "0"))
        page = client.request("GET", f"/v1/items?since={cursor}")
        caught_up = not store.db.execute(
            "SELECT 1 FROM item_info WHERE found = 1 AND name IS NOT NULL AND rowid > ?",
            (int(store.get_meta("sync.up.items", "0")),)).fetchone()
        for _, *r in page["rows"]:
            cur = store.db.execute(
                f"INSERT INTO item_info (found, fetched_ts, {_ITEM_COLS}) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(item_key) DO UPDATE SET found = 1, fetched_ts = excluded.fetched_ts, name = excluded.name, "
                "grade = excluded.grade, grade_name = excluded.grade_name, category = excluded.category, "
                "type = excluded.type, icon = excluded.icon WHERE item_info.found = 0", (now, *r))
            new += max(cur.rowcount, 0)
        store.db.commit()
        if caught_up:                                # what just came down is not sent back up
            top = store.db.execute("SELECT COALESCE(MAX(rowid), 0) FROM item_info").fetchone()[0]
            store.set_meta("sync.up.items", str(top))
        store.set_meta("sync.down.items", str(page["next"]))
        if not page["more"]:
            return new


def shared_alerts(store: Store, new_snaps, notifier, now: float) -> list[str]:
    """Alerts for watched items from prices other users just saw on this computer's market server."""
    home = store.home_server()
    newest: dict[str, tuple[float, float]] = {}
    for server_id, key, ts, price in new_snaps:
        if server_id == home and ts >= now - ALERT_WINDOW and ts >= newest.get(key, (0, 0))[0]:
            newest[key] = (ts, price)
    lines = []
    for alert in alerts.check(store, {k: p for k, (_, p) in newest.items()}, now):
        lines.append(f"!!! BİLDİRİM (ortak veri) {alert.text()}")
        if notifier is not None:
            lines += [f"    gönderilemedi: {e}" for e in notifier(alert)]
    return lines


def sync_once(store: Store, client: ShareClient, notifier=None, now: float | None = None) -> list[str]:
    now = now or time.time()
    try:
        up_s, up_l = upload_pending(store, client)
        new_snaps, new_lists = download_new(store, client)
    except ShareError as e:
        store.set_meta("sync.last_error", str(e)[:200])
        return [f"Ortak veri eşitlenemedi: {e}"]
    store.set_meta("sync.last_ok", str(now))
    store.db.execute("DELETE FROM meta WHERE key = 'sync.last_error'")
    store.db.commit()
    lines = []
    try:                       # kept apart so a store without /v1/items still shares prices
        up_i, new_items = upload_items(store, client), download_items(store, client, now)
        if up_i or new_items:
            lines.append(f"Item adları: {up_i} gönderildi, {new_items} alındı")
    except ShareError as e:
        lines.append(f"Item adları eşitlenemedi: {e}")
    if up_s or up_l or new_snaps or new_lists:
        items = len({(s, k) for s, k, _, _ in new_snaps})
        lines.append(f"Ortak veri: {up_s + up_l} kayıt gönderildi, {len(new_snaps)} fiyat ({items} item) "
                     f"ve {new_lists} ilan alındı")
    return lines + shared_alerts(store, new_snaps, notifier, now)


def _admin(args) -> int:
    c = ShareClient(args.url, args.admin_token)
    if args.action == "create-key":
        r = c.request("POST", "/v1/admin/keys", {"name": " ".join(args.rest)})
        print(f"#{r['id']} {r['name']}\nAnahtar (sadece şimdi gösteriliyor): {r['key']}")
    elif args.action == "list":
        for k in c.request("GET", "/v1/admin/keys")["contributors"]:
            seen = time.strftime("%Y-%m-%d %H:%M", time.localtime(k["last_seen_ts"])) if k["last_seen_ts"] else "-"
            print(f"#{k['id']:<3} {'aktif' if k['active'] else 'iptal':<6} {k['name']:<20} "
                  f"{k['snapshots']:>8} fiyat  son görülme {seen}")
    elif args.action == "revoke":
        print(c.request("POST", "/v1/admin/keys/revoke", {"id": int(args.rest[0])}))
    elif args.action == "purge":
        print(c.request("POST", "/v1/admin/purge", {"contributor_id": int(args.rest[0])}))
    elif args.action == "server-name":
        print(c.request("POST", "/v1/admin/servers", {"server_id": int(args.rest[0]), "name": " ".join(args.rest[1:])}))
    return 0


def main(argv: list[str] | None = None) -> int:
    from .service import DEFAULT_DB

    ap = argparse.ArgumentParser(description="Ortak market verisini eşitler.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("setup", help="başka bir ortak depo kullan (anahtar verilmezse kendisi alır)")
    p.add_argument("url")
    p.add_argument("key", nargs="?")
    sub.add_parser("now", help="hemen eşitle")
    sub.add_parser("status", help="eşitleme durumunu göster")
    sub.add_parser("disable", help="ortak veriyi kapat")
    sub.add_parser("enable", help="ortak veriyi aç")
    p = sub.add_parser("admin", help="depo sahibi: anahtar ve sunucu yönetimi")
    p.add_argument("--url", required=True)
    p.add_argument("--admin-token", required=True)
    p.add_argument("action", choices=["create-key", "list", "revoke", "purge", "server-name"])
    p.add_argument("rest", nargs="*")
    args = ap.parse_args(argv)

    if args.cmd == "admin":
        try:
            return _admin(args)
        except ShareError as e:
            print(f"Hata: {e}")
            return 1
    store = Store(args.db)
    try:
        if args.cmd == "setup":
            try:
                if args.key:
                    invited = ShareClient(args.url, args.key)
                    invited.request("GET", "/v1/servers")
                    store.set_meta("sync.url", invited.url)
                    store.set_meta("sync.key", args.key)
                else:
                    register(store, args.url)
            except ShareError as e:
                print(f"Bağlanılamadı: {e}")
                return 1
            set_enabled(store, True)
            print("Kaydedildi. Servis çalışırken her dakika eşitlenir; şimdi denemek için: sync now")
            return 0
        if args.cmd in ("disable", "enable"):
            set_enabled(store, args.cmd == "enable")
            print("Ortak veri " + ("açıldı." if args.cmd == "enable" else "kapatıldı."))
            return 0
        if args.cmd == "status":
            last = store.get_meta("sync.last_ok")
            print(f"Adres: {share_url(store) or 'yok'} ({'açık' if enabled(store) else 'kapalı'}, "
                  f"{'anahtar var' if store.get_meta('sync.key') else 'anahtar henüz yok'})")
            print(f"Son başarılı eşitleme: {time.ctime(float(last)) if last else '-'}")
            print(f"Son hata: {store.get_meta('sync.last_error') or '-'}")
            print(f"Sunucular: {store.servers()}")
            return 0
        client = ensure_client(store)
        if client is None:
            print(store.get_meta("sync.last_error") if enabled(store) and share_url(store)
                  else "Ortak veri kapalı ya da depo adresi yok (sync enable / sync setup <adres>).")
            return 1
        for line in sync_once(store, client) or ["Yeni veri yok."]:
            print(line)
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
