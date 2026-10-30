import json

from test_tls13 import _record

from aion2market.service import Tracker
from aion2market.store import Store
from aion2market.tls13 import KeyLog, client_hello_sni

CR = bytes(range(32))
C_APP, S_APP = b"\x0c" * 32, b"\x05" * 32


def _client_hello(host: str) -> bytes:
    name = host.encode()
    sni = (len(name) + 3).to_bytes(2, "big") + b"\x00" + len(name).to_bytes(2, "big") + name
    ext = b"\x00\x00" + len(sni).to_bytes(2, "big") + sni
    body = b"\x03\x03" + CR + b"\x00" + b"\x00\x02\x13\x01" + b"\x01\x00" + len(ext).to_bytes(2, "big") + ext
    hs = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + len(hs).to_bytes(2, "big") + hs


def _server_hello() -> bytes:
    body = b"\x03\x03" + b"\x00" * 32 + b"\x00" + b"\x13\x01" + b"\x00" + b"\x00\x00"
    hs = b"\x02" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x03" + len(hs).to_bytes(2, "big") + hs


def _http(start: str, body: dict) -> bytes:
    b = json.dumps(body).encode()
    return f"{start}\r\ncontent-length: {len(b)}\r\n\r\n".encode() + b


def _pkt(c2s: bool, seq: int, payload: bytes, rst=False):
    a, b = ("10.0.0.2", 50000), ("34.117.142.223", 443)
    (src, sport), (dst, dport) = (a, b) if c2s else (b, a)
    return {"src": src, "sport": sport, "dst": dst, "dport": dport, "seq": seq, "payload": payload,
            "syn": False, "fin": False, "rst": rst}


def test_client_hello_sni():
    assert client_hello_sni(_client_hello("qos-api.g.nc.com")) == "qos-api.g.nc.com"
    assert client_hello_sni(b"\x17\x03\x03\x00\x10" + b"\x00" * 60) is None


def test_tracker_stores_listing_after_keys_arrive(tmp_path):
    keyfile = tmp_path / "keys.log"
    store = Store(":memory:")
    store.set_name("610610015", "Pure Odyle")
    store.watch("610610015", 90000, 0)
    sent = []
    tracker = Tracker(KeyLog(keyfile), store, notifier=lambda a: sent.append(a) or [])

    hello = _client_hello("qos-api.g.nc.com")
    req = _record(C_APP, 0, 23, _http(
        "POST /trade/v1.0/sales/valid/pages HTTP/1.1",
        {"game_server_id": "12306", "page_no": 1, "game_item_keys": "610610015"}))
    sale = {"sale_id": "A", "game_item_key": "610610015", "game_item_quantity": "1", "sale_price": "81999",
            "unit_price": "81999.0000", "grade_id": "3", "category_id": "53"}
    resp_plain = _http("HTTP/1.1 200 OK", {"sales": [sale], "loaded": "2026-10-29T23:37:29.000+09:00"})
    resp = _record(S_APP, 0, 23, resp_plain)

    assert tracker.on_packet(_pkt(True, 1000, hello)) == []
    assert tracker.on_packet(_pkt(False, 5000, _server_hello())) == []
    # Response split over two segments, and its first half arriving before the request.
    sh = len(_server_hello())
    assert tracker.on_packet(_pkt(False, 5000 + sh, resp[:40])) == []
    assert tracker.on_packet(_pkt(True, 1000 + len(hello), req)) == []
    assert tracker.on_packet(_pkt(False, 5000 + sh + 40, resp[40:])) == []
    assert tracker.on_packet(_pkt(False, 9999, b"", rst=False)) == []      # empty ACK

    # Keys show up in the log later; poll() picks them up.
    keyfile.write_text(f"CLIENT_TRAFFIC_SECRET_0 {CR.hex()} {C_APP.hex()}\n"
                       f"SERVER_TRAFFIC_SECRET_0 {CR.hex()} {S_APP.hex()}\n")
    lines = tracker.poll()
    assert lines and "Pure Odyle" in lines[0] and "81.999" in lines[0]
    ts, rows = store.latest_listings("610610015")
    assert rows == [(1, 81999, 81999.0)]
    assert [a.price for a in sent] == [81999] and "BİLDİRİM" in lines[-1]


def test_other_hosts_are_ignored(tmp_path):
    tracker = Tracker(KeyLog(tmp_path / "none.log"), Store(":memory:"))
    tracker.on_packet(_pkt(True, 1, _client_hello("lime-frankfurt-p4-api.plaync.com")))
    assert tracker.conns == {}
