import struct

from aion2market import dashboard
from aion2market.inventory import INVENTORY_OPCODE, GameTracker, parse_inventory
from aion2market.store import Store

NOW = 1_800_000_000.0
DAY = 86400


_ids = iter(range(1, 60000))


def _record(key: int, count: int, tail: bytes = b"\x01\x1d" + bytes(13)) -> bytes:
    # 8-byte id (unique, ends in two zero bytes) | u32 key | u64 count | container (1 = bag) | slot/flags
    return b"\x54" + struct.pack("<H", next(_ids)) + b"\x00\x00\x25\x00\x00" + struct.pack("<IQ", key, count) + tail


def _payload(*records: bytes) -> bytes:
    return b"\x10\x02\xe1\x01\x00\xb8\xd1\x0d\x00\x00\x4b\x00" + b"".join(records)


def test_parse_inventory_sums_slots_and_skips_lookalikes():
    noise = b"\x00\x01" + struct.pack("<I", 610610015) + struct.pack("<Q", 9231951234095710525)  # key, bogus count
    payload = _payload(_record(610610015, 15), _record(510716014, 9), _record(610610015, 3), noise,
                       _record(510716014, 40, b"\x0f\x02" + bytes(13)),                    # warehouse: not counted
                       b"\x07\x08" + struct.pack("<IQ", 510716014, 5))                       # no zero bytes before
    assert parse_inventory(payload, {610610015, 510716014}) == {"610610015": 18, "510716014": 9}


def _frame(opcode: int, payload: bytes) -> bytes:
    body = opcode.to_bytes(2, "little") + payload
    out, v = bytearray(), len(body) + 4          # framing: varint L, then L - 4 bytes of body
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            break
    return bytes(out) + body


def _pkt(seq, payload, src=("1.2.3.4", 7777), dst=("127.0.0.1", 50000)):
    return {"t": NOW, "src": src[0], "sport": src[1], "dst": dst[0], "dport": dst[1], "seq": seq,
            "payload": payload, "syn": False, "fin": False, "rst": False}


def test_tracker_stores_inventory_from_the_server_stream_even_if_seen_before_the_connection_is_known():
    s = Store(":memory:")
    s.add_snapshots(NOW, 12306, [("610610015", 50000.0, 10), ("510716014", 2000.0, 3)])
    game = GameTracker(s)
    stream = _frame(0x3600, b"\x00" * 20) + _frame(INVENTORY_OPCODE, _payload(_record(610610015, 7),
                                                                                _record(510716014, 2)))
    half = len(stream) // 2
    assert game.on_packet(_pkt(100, stream[:half])) == []                 # connection not known yet: buffered
    lines = game.set_connections({("127.0.0.1", 50000, "1.2.3.4", 7777)})
    lines += game.on_packet(_pkt(100 + half, stream[half:]))
    assert any("Envanter kaydedildi: 2 çeşit" in l for l in lines)
    assert s.latest_inventory()[1] == {"610610015": 7, "510716014": 2}
    # client -> server packets of the same connection are ignored
    assert game.on_packet(_pkt(5, b"\xff" * 30, src=("127.0.0.1", 50000), dst=("1.2.3.4", 7777))) == []


def test_inventory_view_signals():
    s = Store(":memory:")
    for d in (20, 15, 10, 8, 6, 4, 2):
        s.add_snapshots(NOW - d * DAY, 12306, [("up", 100.0, 5), ("down", 100.0, 5), ("flat", 100.0, 5)])
    s.add_snapshots(NOW - 60, 12306, [("up", 130.0, 5), ("down", 80.0, 5), ("flat", 101.0, 5)])
    s.set_inventory(NOW - 30, {"up": 10, "down": 4, "flat": 1, "gone": 3})
    import time as _t
    real = _t.time
    _t.time = lambda: NOW
    try:
        v = dashboard.inventory_view(s, 12306)
    finally:
        _t.time = real
    by = {i["item_key"]: i for i in v["items"]}
    assert by["up"]["signal"] == "sell" and by["up"]["suggest_price"] == 129 and by["up"]["value_net"] == 1144
    assert by["down"]["signal"] == "hold" and by["flat"]["signal"] == "normal"
    assert [u["item_key"] for u in v["unpriced"]] == ["gone"]
    assert v["sell_value"] == 1144 and v["total_value"] == 1144 + round(4 * 80 * 0.88) + round(101 * 0.88)
