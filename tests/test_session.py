import json
import time

from scapy.all import IP, TCP, Ether, Raw

from aion2market.capture import Session
from aion2market.procnet import ConnKey

KEY = ConnKey("192.168.1.10", 50000, "1.2.3.4", 7777)


def pkt(c2s: bool, seq: int, data: bytes = b"", flags: str = "PA", t: float = 0.0):
    if c2s:
        p = Ether() / IP(src=KEY.local_ip, dst=KEY.remote_ip) / TCP(sport=KEY.local_port, dport=KEY.remote_port, seq=seq, flags=flags)
    else:
        p = Ether() / IP(src=KEY.remote_ip, dst=KEY.local_ip) / TCP(sport=KEY.remote_port, dport=KEY.local_port, seq=seq, flags=flags)
    if data:
        p = p / Raw(data)
    p.time = t
    return p


def test_session_records_both_directions_and_replays_early_packets(tmp_path):
    s = Session(tmp_path / "run", write_pcap=True)
    now = time.time()
    # Arrives before psutil reports the connection -> buffered, then replayed.
    s.on_packet(pkt(True, 99, flags="S", t=now))
    s.on_packet(pkt(True, 100, b"hello", t=now))
    s.add_connections({KEY})
    s.on_packet(pkt(False, 500, b"WORLD", t=now))
    s.on_packet(pkt(True, 108, b"!", t=now))     # out of order
    s.on_packet(pkt(True, 105, b"abc", t=now))
    s.on_packet(pkt(False, 500, b"WORLD", t=now))  # retransmit
    # Unrelated traffic is ignored.
    other = Ether() / IP(src="10.0.0.1", dst="10.0.0.2") / TCP(sport=1, dport=2, seq=1) / Raw(b"x")
    s.on_packet(other)
    s.close()

    folder = next((tmp_path / "run").glob("conn01_*"))
    assert (folder / "c2s.bin").read_bytes() == b"helloabc!"
    assert (folder / "s2c.bin").read_bytes() == b"WORLD"
    events = [json.loads(l) for l in (tmp_path / "run" / "index.jsonl").read_text().splitlines()]
    assert events[0]["event"] == "open"
    assert sum(e["len"] for e in events if e["event"] == "data") == 14
    assert (tmp_path / "run" / "raw.pcap").stat().st_size > 0
    assert "conn01_" in s.summary()


def test_ethernet_padding_is_not_payload(tmp_path):
    s = Session(tmp_path / "run", write_pcap=False)
    s.add_connections({KEY})
    ack = pkt(False, 500, flags="A", t=time.time())
    padded = Ether(bytes(ack) + b"\x00" * 6)  # short frame padded to 60 bytes
    s.on_packet(padded)
    s.close()
    folder = next((tmp_path / "run").glob("conn01_*"))
    assert (folder / "s2c.bin").read_bytes() == b""
