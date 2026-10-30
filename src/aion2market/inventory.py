"""The character's inventory, read passively from the game server's own messages.

At login the server sends opcode 0x5611: the whole inventory as records of
    8 bytes id | u32 item key | u64 count | more bytes (slot, flags, ...)
Records differ in length by item type, so instead of walking them we look for
known market item keys and validate each hit: the two bytes before the key are
zero and the count is sensible. Bytes that only look like a key fail that.

Only server->client data is read; nothing is sent to the game.

    python -m aion2market.inventory import captures\\<run>    # latest inventory from a recording
"""
from __future__ import annotations

import argparse
import struct
import time
from collections import deque
from pathlib import Path

from .protocol import FrameError, parse_stream
from .reassembly import Data, Gap, StreamReassembler
from .store import Store

INVENTORY_OPCODE = 0x5611
MAX_COUNT = 1_000_000
MAX_BUFFER = 8 * 1024 * 1024          # unparseable stream (joined mid-way): give up on it
PENDING_SECONDS = 15.0                 # keep packets of not-yet-identified connections this long


def parse_inventory(payload: bytes, known_keys: set[int]) -> dict[str, int]:
    """item key -> total count (an item in several slots is summed)."""
    out: dict[str, int] = {}
    for i in range(10, len(payload) - 12):
        key = struct.unpack_from("<I", payload, i)[0]
        if key not in known_keys or payload[i - 2] or payload[i - 1]:
            continue
        count = struct.unpack_from("<Q", payload, i + 4)[0]
        if 0 < count < MAX_COUNT:
            out[str(key)] = out.get(str(key), 0) + count
    return out


def known_keys(store: Store) -> set[int]:
    rows = store.db.execute("SELECT item_key FROM item_info WHERE found = 1 UNION SELECT item_key FROM exchange_names "
                            "UNION SELECT item_key FROM price_snapshots")
    return {int(k) for (k,) in rows if str(k).isdigit()}


class GameConnection:
    def __init__(self):
        self.stream = StreamReassembler()
        self.buf = bytearray()
        self.broken = False


class GameTracker:
    """Follows the game connection's server->client stream and stores every inventory it carries.

    ``set_connections`` gets the game's TCP connections (local ip, local port, remote ip, remote port)
    from the process table; packets seen shortly before a connection is known are replayed."""

    def __init__(self, store: Store):
        self.store = store
        self.conns: dict[tuple, GameConnection] = {}
        self.pending: deque = deque(maxlen=50_000)
        self._keys: set[int] | None = None

    def set_connections(self, keys: set[tuple]) -> list[str]:
        lines = []
        for key in keys - self.conns.keys():
            self.conns[key] = GameConnection()
            lines += self._replay()
        for key in self.conns.keys() - keys:
            del self.conns[key]
        return lines

    def _replay(self) -> list[str]:
        lines, keep = [], deque(maxlen=self.pending.maxlen)
        cutoff = time.time() - PENDING_SECONDS
        for p in self.pending:
            if self._match(p):
                lines += self.on_packet(p, buffer_unknown=False)
            elif p["t"] >= cutoff:
                keep.append(p)
        self.pending = keep
        return lines

    def _match(self, p) -> GameConnection | None:
        # only the server -> client direction: source is the remote end of a known connection
        return self.conns.get((p["dst"], p["dport"], p["src"], p["sport"]))

    def on_packet(self, p: dict, buffer_unknown: bool = True) -> list[str]:
        conn = self._match(p)
        if conn is None:
            if buffer_unknown and p["payload"]:
                self.pending.append(p)
            return []
        if conn.broken:
            return []
        lines = []
        for ev in conn.stream.feed(p["seq"], p["payload"], syn=p["syn"]):
            if isinstance(ev, Gap):
                conn.broken = True          # framing is lost; the next login starts a new connection
                return lines
            if isinstance(ev, Data):
                conn.buf += ev.payload
        try:
            frames, used = parse_stream(bytes(conn.buf))
        except FrameError:
            conn.broken = True
            return lines
        del conn.buf[:used]
        if len(conn.buf) > MAX_BUFFER:
            conn.broken = True
        for f in frames:
            if f.opcode == INVENTORY_OPCODE:
                lines.append(self._store_inventory(f.payload, p["t"]))
        return lines

    def _store_inventory(self, payload: bytes, ts: float) -> str:
        if self._keys is None or len(self._keys) < 100:
            self._keys = known_keys(self.store)
        items = parse_inventory(payload, self._keys)
        self.store.set_inventory(ts, items)
        return f"Envanter kaydedildi: {len(items)} çeşit item, toplam {sum(items.values())} adet"


def import_run(store: Store, run: Path) -> tuple[float, dict[str, int]] | None:
    """Store the last inventory found in a capture folder (as written by aion2market.capture)."""
    from .report import load_frames
    found = None
    for t, _, f in load_frames(run):
        if f.opcode == INVENTORY_OPCODE:
            found = (t, f.payload)
    if found is None:
        return None
    items = parse_inventory(found[1], known_keys(store))
    store.set_inventory(found[0], items)
    return found[0], items


def main(argv: list[str] | None = None) -> int:
    from .service import DEFAULT_DB

    ap = argparse.ArgumentParser(description="Envanteri kayıtlı bir yakalamadan içe aktarır.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="captures\\<kayıt> klasöründeki son envanteri kaydet")
    p.add_argument("run", type=Path)
    args = ap.parse_args(argv)
    store = Store(args.db)
    try:
        res = import_run(store, args.run)
        if res is None:
            print("Bu kayıtta envanter mesajı yok (oyuna giriş anı kaydedilmemiş olabilir).")
            return 1
        ts, items = res
        print(f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(ts))}: {len(items)} çeşit item kaydedildi.")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
