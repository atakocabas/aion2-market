"""The character's inventory, read passively from the game server's own messages.

At login the server sends opcode 0x5611: every stack the character owns as records of
    8 bytes id | u32 item key | u64 count | u8 container | u16 slot | more bytes (flags, ...)
Records differ in length by item type, so instead of walking them we look for
known market item keys and validate each hit: the two bytes before the key are
zero and the count is sensible. Bytes that only look like a key fail that.
Container 1 is the bag (stored), 15 the warehouse (stored separately), 11 equipped, 4 transient pickups, others unknown.

During play 0x561b lists changed stacks: u8 n, then n records of
    u8 op (0 add, 1 update, 2 remove) | u8 ext | the same id/key/count/container/slot | tail
where count is the stack's new total. Ids only mean something within one connection.

Only server->client data is read; nothing is sent to the game.

    python -m aion2market.inventory import captures\\<run>    # latest inventory from a recording
"""
from __future__ import annotations

import argparse
import struct
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .protocol import FrameError, parse_stream
from .reassembly import Data, Gap, StreamReassembler
from .store import Store

INVENTORY_OPCODE = 0x5611
MAX_COUNT = 1_000_000
MAX_BUFFER = 8 * 1024 * 1024          # unparseable stream (joined mid-way): give up on it
PENDING_SECONDS = 15.0                 # keep packets of not-yet-identified connections this long


CHANGE_OPCODE = 0x561b
CONTAINER_INVENTORY = 1
CONTAINER_WAREHOUSE = 15
CONTAINER_TRANSIENT = 4                # picked up and used ~0.1 s later
ADD, UPDATE, REMOVE = 0, 1, 2


@dataclass(frozen=True)
class Stack:
    item_key: str
    count: int
    container: int


def parse_login(payload: bytes, known_keys: set[int]) -> dict[bytes, Stack]:
    """Every stack of a 0x5611 (all containers), by its 8-byte id."""
    out: dict[bytes, Stack] = {}
    for i in range(10, len(payload) - 12):
        key = struct.unpack_from("<I", payload, i)[0]
        if key not in known_keys or payload[i - 2] or payload[i - 1]:
            continue
        count = struct.unpack_from("<Q", payload, i + 4)[0]
        if 0 < count < MAX_COUNT:
            out[bytes(payload[i - 8:i])] = Stack(str(key), count, payload[i + 12])
    return out


def _change_at(payload: bytes, p: int) -> bool:
    # p = start of the id: id bytes 3, 4, 6, 7 are zero, then a plausible key, count and container
    if p + 23 > len(payload) or payload[p + 3] or payload[p + 4] or payload[p + 6] or payload[p + 7]:
        return False
    key, count = struct.unpack_from("<IQ", payload, p + 8)
    return 100_000_000 <= key < 1_000_000_000 and count < 2 ** 32 and 1 <= payload[p + 20] <= 63


def parse_changes(payload: bytes) -> list[tuple[int, bytes, Stack]]:
    """The records of a 0x561b as (op, id, stack). Tails differ in length, so each later record is
    searched for from 39 bytes past the previous id."""
    n, out, p = payload[0] if payload else 0, [], 3
    while len(out) < n:
        while p + 23 <= len(payload) and not _change_at(payload, p):
            p += 1
        if p + 23 > len(payload):
            raise ValueError(f"0x561b: {len(out)} of {n} records found")
        key, count = struct.unpack_from("<IQ", payload, p + 8)
        out.append((payload[p - 2], bytes(payload[p:p + 8]), Stack(str(key), count, payload[p + 20])))
        p += 39
    return out


def apply_changes(stacks: dict[bytes, Stack], changes: list[tuple[int, bytes, Stack]],
                  known_keys: set[int]) -> bool:
    """Apply 0x561b records to a login's stacks; True if a bag total changed. Skipped like at login:
    transient pickups and items the market doesn't know; updates of a stack never seen are skipped too."""
    before = totals(stacks)
    for op, sid, st in changes:
        if st.container == CONTAINER_TRANSIENT or int(st.item_key) not in known_keys:
            continue
        if op == REMOVE or (op in (ADD, UPDATE) and st.count >= MAX_COUNT):    # a login would drop it too
            stacks.pop(sid, None)
        elif op == ADD or (op == UPDATE and sid in stacks):
            stacks[sid] = st
    return totals(stacks) != before


def totals(stacks: dict[bytes, Stack], container: int = CONTAINER_INVENTORY) -> dict[str, int]:
    """item key -> total count in one container (an item in several slots is summed)."""
    out: dict[str, int] = {}
    for st in stacks.values():
        if st.container == container:
            out[st.item_key] = out.get(st.item_key, 0) + st.count
    return out


def parse_inventory(payload: bytes, known_keys: set[int]) -> dict[str, int]:
    """item key -> total count in the bag."""
    return totals(parse_login(payload, known_keys))


def known_keys(store: Store) -> set[int]:
    rows = store.db.execute("SELECT item_key FROM item_info WHERE found = 1 UNION SELECT item_key FROM exchange_names "
                            "UNION SELECT item_key FROM price_snapshots")
    return {int(k) for (k,) in rows if str(k).isdigit()}


class GameConnection:
    def __init__(self):
        self.stream = StreamReassembler()
        self.buf = bytearray()
        self.broken = False
        self.stacks: dict[bytes, Stack] | None = None     # from this connection's login, kept current


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
            lines += self.on_frame(conn, f.opcode, f.payload, p["t"])
        return lines

    def on_frame(self, conn: GameConnection, opcode: int, payload: bytes, ts: float) -> list[str]:
        if opcode == INVENTORY_OPCODE:
            conn.stacks = parse_login(payload, self._known())
            items = totals(conn.stacks)
            self.store.set_inventory(ts, items)
            self.store.set_warehouse(ts, totals(conn.stacks, CONTAINER_WAREHOUSE))
            return [f"Envanter kaydedildi: {len(items)} çeşit item, toplam {sum(items.values())} adet"]
        if opcode == CHANGE_OPCODE and conn.stacks is not None:     # joined mid-session: no ids to apply to
            try:
                changes = parse_changes(payload)
            except ValueError:
                return []
            warehouse = totals(conn.stacks, CONTAINER_WAREHOUSE)
            if apply_changes(conn.stacks, changes, self._known()):
                self.store.update_inventory(ts, totals(conn.stacks))   # silent: loot would flood the log
            if totals(conn.stacks, CONTAINER_WAREHOUSE) != warehouse:
                self.store.update_warehouse(ts, totals(conn.stacks, CONTAINER_WAREHOUSE))
        return []

    def _known(self) -> set[int]:
        if self._keys is None or len(self._keys) < 100:
            self._keys = known_keys(self.store)
        return self._keys


def import_run(store: Store, run: Path) -> tuple[float, dict[str, int]] | None:
    """Store the last inventory (bag and warehouse) found in a capture folder (as written by aion2market.capture)."""
    from .report import load_frames
    found = None
    for t, _, f in load_frames(run):
        if f.opcode == INVENTORY_OPCODE:
            found = (t, f.payload)
    if found is None:
        return None
    stacks = parse_login(found[1], known_keys(store))
    items = totals(stacks)
    store.set_inventory(found[0], items)
    store.set_warehouse(found[0], totals(stacks, CONTAINER_WAREHOUSE))
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
