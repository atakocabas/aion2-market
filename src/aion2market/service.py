"""Live market price recorder.

Passively listens to HTTPS traffic, picks the game's market connections by
their TLS server name, decrypts them with the keys the game's libcurl writes
to SSLKEYLOGFILE and stores every market search result in SQLite. Nothing is
sent to the game or its servers; the only outgoing requests are slow lookups of
item names on NC's public website (see iteminfo.py, off with --no-item-info).

    python -m aion2market.service run                      # live, until Ctrl+C
    python -m aion2market.service replay captures\\<run>    # backfill from a recording
    python -m aion2market.service name 610610015 "Pure Odyle"
    python -m aion2market.service show [item]
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from . import alerts, exchange, iteminfo, sync
from .http1 import HttpStream
from .inventory import GameTracker
from .market import MARKET_HOST, fmt_price, handle_exchange
from .procnet import DEFAULT_PROCESS_PATTERN, find_game_pids, game_connections
from .reassembly import Data, Gap, StreamReassembler
from .store import Store
from .tls13 import KeyLog, TlsConnection, client_hello_sni

DEFAULT_DB = Path("data") / "market.db"
DEFAULT_KEYLOG = Path("captures") / "sslkeys.log"
IDLE_SECONDS = 120.0


class MarketConnection:
    def __init__(self, keylog: KeyLog):
        self.streams = {"c2s": StreamReassembler(), "s2c": StreamReassembler()}
        self.tls = TlsConnection(keylog)
        self.http = {"c2s": HttpStream(), "s2c": HttpStream()}
        self.requests: deque = deque()
        self.broken = False
        self.last_seen = time.time()


class Tracker:
    """Follows market TLS connections packet by packet and stores what they carry."""

    def __init__(self, keylog: KeyLog, store: Store, host: str = MARKET_HOST, notifier=None):
        self.keylog = keylog
        self.store = store
        self.host = host
        self.notifier = notifier            # None: don't evaluate alerts (e.g. replays of old data)
        self.conns: dict[tuple, MarketConnection] = {}

    def on_packet(self, p: dict) -> list[str]:
        key = (p["src"], p["sport"], p["dst"], p["dport"])
        back = (p["dst"], p["dport"], p["src"], p["sport"])
        if key in self.conns:
            conn, direction = self.conns[key], "c2s"
        elif back in self.conns:
            conn, direction = self.conns[back], "s2c"
        elif p["payload"] and self.host in (client_hello_sni(p["payload"]) or ""):
            conn, direction = MarketConnection(self.keylog), "c2s"
            self.conns[key] = conn
        else:
            return []
        conn.last_seen = time.time()
        lines = []
        if not conn.broken:
            for ev in conn.streams[direction].feed(p["seq"], p["payload"], syn=p["syn"]):
                if isinstance(ev, Gap):
                    conn.broken = True         # lost TLS record boundaries; nothing more to decrypt
                    break
                if isinstance(ev, Data) and ev.payload:
                    lines += self._on_plain(conn, conn.tls.feed(direction, ev.payload))
        if p["rst"]:
            self.conns.pop(key if key in self.conns else back, None)
        return lines

    def _on_plain(self, conn: MarketConnection, chunks) -> list[str]:
        lines = []
        for direction, data in chunks:
            for msg in conn.http[direction].feed(data):
                if direction == "c2s":
                    conn.requests.append(msg)
                elif conn.requests:
                    observed: dict[str, float] = {}
                    lines += handle_exchange(self.store, conn.requests.popleft(), msg, observed=observed)
                    if self.notifier is not None and observed:
                        for alert in alerts.check(self.store, observed, time.time()):
                            lines.append(f"!!! BİLDİRİM {alert.text()}")
                            lines += [f"    gönderilemedi: {e}" for e in self.notifier(alert)]
        return lines

    def poll(self) -> list[str]:
        """Retry connections still waiting for their keys and drop idle ones."""
        lines = []
        now = time.time()
        for key, conn in list(self.conns.items()):
            if conn.tls.waiting:
                lines += self._on_plain(conn, conn.tls.drain())
            if now - conn.last_seen > IDLE_SECONDS:
                del self.conns[key]
        return lines


def replay(run: Path, keylog: KeyLog, store: Store, host: str = MARKET_HOST) -> list[str]:
    """Process a capture folder (c2s.bin / s2c.bin per connection)."""
    lines = []
    tracker = Tracker(keylog, store, host)
    for d in sorted(p for p in run.iterdir() if (p / "c2s.bin").exists()):
        c2s = (d / "c2s.bin").read_bytes()
        if host not in (client_hello_sni(c2s[:4096]) or ""):
            continue
        conn = MarketConnection(keylog)
        lines += tracker._on_plain(conn, conn.tls.feed("c2s", c2s))
        lines += tracker._on_plain(conn, conn.tls.feed("s2c", (d / "s2c.bin").read_bytes()))
    return lines


def default_keylog() -> Path:
    # The variable is set for the user; a shell started earlier may not have it yet.
    env = os.environ.get("SSLKEYLOGFILE")
    if not env and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                env = winreg.QueryValueEx(k, "SSLKEYLOGFILE")[0]
        except OSError:
            env = None
    return Path(env) if env else DEFAULT_KEYLOG


def _once(what: str, db: Path, body) -> None:
    """One round of a background loop; an unexpected error is logged instead of ending the loop for good."""
    try:
        store = Store(db)
    except Exception as e:
        print(f"{what}: veritabanı açılamadı: {e}", flush=True)
        return
    try:
        body(store)
    except Exception:
        import traceback
        print(f"{what}: beklenmeyen hata (sonra tekrar denenecek)", flush=True)
        traceback.print_exc()
    finally:
        store.close()


def _item_info_loop(db: Path, stop: threading.Event, every: float = 300.0) -> None:
    """Look up official names for newly seen items in the background."""
    def body(store):
        found, _, errors = iteminfo.fill_missing(store, stop=stop.is_set)
        if found:
            print(f"{found} yeni item adı resmi veriden eklendi", flush=True)
        if errors:
            print(f"Item adı sorgusunda {errors} hata (sonra tekrar denenecek)", flush=True)
    while not stop.is_set():
        _once("Item adları", db, body)
        stop.wait(every)


def _sync_loop(db: Path, stop: threading.Event, notifier, every: float = 60.0) -> None:
    """Share observations with the other users while sharing is on (it can be switched in the window)."""
    def body(store):
        client = sync.ensure_client(store)
        if client is not None:
            for line in sync.sync_once(store, client, notifier):
                print(line, flush=True)
    while not stop.is_set():
        _once("Ortak veri", db, body)
        stop.wait(every)


def _exchange_loop(db: Path, stop: threading.Event, notifier) -> None:
    """Pull prices for this computer's market server (or the chosen one) from aion2.exchange every few minutes."""
    def body(store):
        if exchange.server_of(store) is not None:
            for line in exchange.import_once(store, notifier=notifier):
                print(line, flush=True)
    while not stop.is_set():
        _once("aion2.exchange", db, body)
        stop.wait(exchange.INTERVAL)


def run_background(db: Path, stop_file: Path, notifier=None) -> None:
    """Without Npcap: only the sources that need no capture (item names, shared store, aion2.exchange)."""
    notifier = notifier or alerts.Notifier()
    stop = threading.Event()
    threading.Thread(target=_item_info_loop, args=(db, stop), daemon=True).start()
    threading.Thread(target=_sync_loop, args=(db, stop, notifier), daemon=True).start()
    threading.Thread(target=_exchange_loop, args=(db, stop, notifier), daemon=True).start()
    print("Npcap yok: canlı kayıt kapalı, sadece arka plan kaynakları çalışıyor", flush=True)
    try:
        while not stop_file.exists():
            time.sleep(1.0)
        stop_file.unlink()
    finally:
        stop.set()
        notifier.close()


def run_live(args, store: Store) -> int:
    from scapy.all import AsyncSniffer, conf

    from .capture import parse_packet

    keylog = KeyLog(args.keylog)
    notifier = make_notifier(args)
    tracker = Tracker(keylog, store, args.host, notifier)
    packets: queue.Queue = queue.Queue()

    def on_packet(pkt):
        p = parse_packet(pkt)
        if p is not None:
            packets.put(p)

    iface = args.iface or str(conf.iface)
    # The system default may not be where the market traffic goes (VPN, ExitLag, several network cards).
    market_ifaces = [iface] if args.iface else market_interfaces(iface, args.host)
    sniffer = AsyncSniffer(iface=market_ifaces if len(market_ifaces) > 1 else iface, filter="tcp port 443",
                           prn=on_packet, store=False)
    sniffer.start()
    # The game's own connection (inventory). With ExitLag it runs over loopback, so listen there too.
    game, game_sniffer = None, None
    if not args.no_inventory:
        from .capture import _route_iface
        game = GameTracker(store)
        game_packets: queue.Queue = queue.Queue()
        game_ifaces = [iface] + [str(lo) for lo in [_route_iface("127.0.0.1")] if lo is not None and str(lo) != iface]

        def on_game_packet(pkt):
            p = parse_packet(pkt)
            if p is not None and p["payload"]:
                game_packets.put(p)
        game_sniffer = AsyncSniffer(iface=game_ifaces if len(game_ifaces) > 1 else game_ifaces[0],
                                    filter="tcp and not port 443", prn=on_game_packet, store=False)
        game_sniffer.start()
        print("Envanter: oyunun bağlantısı dinleniyor (oyuna her girişte güncellenir)")
    next_game_poll = 0.0
    print(f"Dinleniyor: {', '.join(market_ifaces)}  anahtarlar: {args.keylog}  veritabanı: {args.db}  — durdurmak için Ctrl+C")
    print(f"Bildirim kanalları: {', '.join(notifier.channels) or 'yok'}")
    if not args.keylog.exists():
        print("Uyarı: anahtar dosyası henüz yok. Steam ve oyun SSLKEYLOGFILE ayarlandıktan sonra açılmış olmalı.")
    keylog_seen = None
    stop_file = Path(args.stop_file) if args.stop_file else None
    stop_names = threading.Event()
    if not args.no_item_info:
        threading.Thread(target=_item_info_loop, args=(args.db, stop_names), daemon=True).start()
    if sync.share_url(store):
        print(f"Ortak veri {'açık' if sync.enabled(store) else 'kapalı'}: açıkken her dakika eşitlenir")
    threading.Thread(target=_sync_loop, args=(args.db, stop_names, notifier), daemon=True).start()
    if exchange.server_of(store) is not None:
        print(f"aion2.exchange açık: sunucu {exchange.server_of(store)}, "
              f"{exchange.INTERVAL // 60} dakikada bir")
    # Always running: the server becomes known once the game opens the market.
    threading.Thread(target=_exchange_loop, args=(args.db, stop_names, notifier), daemon=True).start()
    next_poll = time.time() + 1.0
    try:
        while True:
            try:
                for line in tracker.on_packet(packets.get(timeout=0.5)):
                    print(line, flush=True)
            except queue.Empty:
                pass
            if game is not None:
                if time.time() >= next_game_poll:
                    pids = set(find_game_pids(DEFAULT_PROCESS_PATTERN))
                    conns = {(c.local_ip, c.local_port, c.remote_ip, c.remote_port)
                             for c in game_connections(pids, {443})} if pids else set()
                    for line in game.set_connections(conns):
                        print(line, flush=True)
                    next_game_poll = time.time() + 2.0
                while not game_packets.empty():
                    for line in game.on_packet(game_packets.get_nowait()):
                        print(f"{datetime.now():%H:%M:%S} {line}", flush=True)
            if time.time() >= next_poll:
                for line in tracker.poll():
                    print(line, flush=True)
                next_poll = time.time() + 1.0
                for s in (sniffer, game_sniffer):
                    if s is not None and getattr(s, "exception", None) is not None:
                        raise RuntimeError(f"paket dinleme durdu: {s.exception}") from s.exception
                seen = args.keylog.exists()
                if seen != keylog_seen:
                    keylog_seen = seen
                    set_capture_status(store, None if seen else KEYLOG_MISSING)
                if stop_file is not None and stop_file.exists():
                    stop_file.unlink()
                    break
    except KeyboardInterrupt:
        pass
    finally:
        stop_names.set()
        sniffer.stop()
        if game_sniffer is not None:
            game_sniffer.stop()
        notifier.close()
    return 0


KEYLOG_MISSING = "anahtar dosyası yok: Steam'i tamamen kapatıp yeniden aç"


def set_capture_status(store: Store, error: str | None) -> None:
    """What the window shows next to Npcap; None means live capture is working."""
    if error:
        store.set_meta("capture.error", error[:200])
    else:
        store.db.execute("DELETE FROM meta WHERE key = 'capture.error'")
        store.db.commit()


def market_interfaces(default: str, host: str = MARKET_HOST) -> list[str]:
    """The default interface plus the one the route to the market server uses, if that differs."""
    import socket

    from .capture import _route_iface
    ifaces = [default]
    try:
        route = _route_iface(socket.gethostbyname(host))
    except OSError:
        route = None
    if route is not None and str(route) not in ifaces:
        ifaces.append(str(route))
    return ifaces


def make_notifier(args) -> alerts.Notifier:
    return alerts.Notifier(popup=not args.no_popup,
                           discord_url=args.discord_webhook or os.environ.get("AION2_DISCORD_WEBHOOK"))


def show(store: Store, query: str | None) -> int:
    if query:
        keys = store.resolve(query)
        if not keys:
            print(f"'{query}' adında item yok. Önce: name <item_key> <ad>")
            return 1
    else:
        keys = [k for k, _ in store.named_items()]
        if not keys:
            print("Adı verilmiş item yok. Örnek: name 610610015 \"Pure Odyle\"")
            return 0
    for key in keys:
        name = store.name(key)
        print(f"{name or key} ({key})" if name else key)
        snap = store.latest_snapshot(key)
        if snap:
            ts, price, count = snap
            print(f"    en düşük birim fiyat {fmt_price(price)}, {count} ilan  [{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}]")
        ts, rows = store.latest_listings(key)
        if rows:
            single = [sale for qty, sale, _ in rows if qty == 1]
            if single:
                print(f"    1 adet en ucuz {fmt_price(min(single))}  [{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M}]")
            for qty, sale, unit in rows[:5]:
                print(f"      {qty:>4} adet  toplam {fmt_price(sale):>12}  birim {fmt_price(unit):>10}")
        if not snap and not rows:
            print("    henüz kayıt yok")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aion 2 market fiyatlarını pasif olarak kaydeder.")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite dosyası (varsayılan: {DEFAULT_DB})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="canlı dinle ve kaydet")
    p_run.add_argument("--keylog", type=Path, default=None, help="SSLKEYLOGFILE yolu (varsayılan: ortam değişkeni)")
    p_run.add_argument("--iface", help="Npcap arayüzü (varsayılan: sistemin varsayılanı)")
    p_run.add_argument("--host", default=MARKET_HOST)
    p_run.add_argument("--stop-file", help="bu dosya oluşunca düzgünce dur")
    p_run.add_argument("--no-inventory", action="store_true",
                       help="oyunun kendi bağlantısını dinleme (envanter kaydedilmez)")
    p_run.add_argument("--no-item-info", action="store_true",
                       help="yeni itemlerin adlarını NCSOFT'un resmi item verisinden sorgulama")

    p_test = sub.add_parser("notify-test", help="yapılandırılmış kanallara deneme bildirimi gönder")
    for p in (p_run, p_test):
        p.add_argument("--no-popup", action="store_true", help="ekranda bildirim kartı gösterme")
        p.add_argument("--discord-webhook", help="Discord webhook URL'si (varsayılan: AION2_DISCORD_WEBHOOK)")

    p_rep = sub.add_parser("replay", help="kayıtlı captures klasörlerini işle")
    p_rep.add_argument("runs", type=Path, nargs="+")
    p_rep.add_argument("--keylog", type=Path, default=None)
    p_rep.add_argument("--host", default=MARKET_HOST)

    p_name = sub.add_parser("name", help="item koduna ad ver")
    p_name.add_argument("item_key")
    p_name.add_argument("name")

    p_show = sub.add_parser("show", help="son fiyatları göster")
    p_show.add_argument("item", nargs="?", help="item kodu ya da adı (boşsa adı verilmiş tüm itemler)")

    args = ap.parse_args(argv)
    store = Store(args.db)
    try:
        if args.cmd == "run":
            args.keylog = args.keylog or default_keylog()
            return run_live(args, store)
        if args.cmd == "replay":
            keylog = KeyLog(args.keylog or default_keylog())
            for run in args.runs:
                for line in replay(run, keylog, store, args.host):
                    print(line)
            return 0
        if args.cmd == "notify-test":
            notifier = make_notifier(args)
            if not notifier.channels:
                print("Hiç bildirim kanalı yok.")
                return 1
            errors = notifier.info("Deneme", "Bildirimler çalışıyor.")
            errors += notifier(alerts.Alert("610610015", "Örnek item", 56470, 57000, time.time()))
            errors += notifier.close(wait=60)          # the cards stay up until they time out
            for e in errors:
                print(f"gönderilemedi: {e}")
            if errors:
                return 1
            print(f"Gönderildi: {', '.join(notifier.channels)}")
            return 0
        if args.cmd == "name":
            store.set_name(args.item_key, args.name)
            print(f"{args.item_key} = {args.name}")
            return 0
        return show(store, args.item)
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
