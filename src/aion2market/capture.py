"""Passively record the game's TCP streams via Npcap.

Nothing is sent to the game or its servers; we only read packets the OS
already delivers. Run from an elevated (Administrator) terminal.

Output layout (one folder per run):

    captures/<YYYYmmdd-HHMMSS>/
        raw.pcap                     # game packets only, for re-analysis in Wireshark
        index.jsonl                  # open/data/gap/close events with timestamps
        conn01_<lport>-<rip>_<rport>/
            c2s.bin                  # client -> server, reassembled
            s2c.bin                  # server -> client, reassembled
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import sys
import threading
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

from scapy.all import IP, TCP, AsyncSniffer, IPv6, PcapWriter, Raw, conf

from .procnet import DEFAULT_PROCESS_PATTERN, ConnKey, find_game_pids, game_connections
from .reassembly import Data, Gap, StreamReassembler

UNKNOWN_BUFFER_SECONDS = 10.0
UNKNOWN_BUFFER_MAX = 50_000
SAMPLE_BYTES = 64 * 1024


def shannon_entropy(data: bytes) -> float:
    if not data:
        return 0.0
    n = len(data)
    return abs(-sum(c / n * math.log2(c / n) for c in Counter(data).values()))


class Direction:
    def __init__(self, path: Path):
        self.file = path.open("wb")
        self.stream = StreamReassembler()
        self.bytes = 0
        self.gaps = 0
        self.sample = bytearray()

    def close(self) -> None:
        self.file.close()


class ConnRecorder:
    def __init__(self, key: ConnKey, folder: Path):
        folder.mkdir(parents=True)
        self.key = key
        self.folder = folder
        self.dirs = {"c2s": Direction(folder / "c2s.bin"), "s2c": Direction(folder / "s2c.bin")}
        self.closed = False


class Session:
    def __init__(self, out_dir: Path, write_pcap: bool):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True)
        self.index = (out_dir / "index.jsonl").open("w", encoding="utf-8")
        self.pcap = PcapWriter(str(out_dir / "raw.pcap"), sync=False) if write_pcap else None
        self.lock = threading.Lock()
        self.conns: dict[ConnKey, ConnRecorder] = {}
        # Packets of not-yet-known connections, so a fresh connection's first
        # packets (handshake, possible key exchange) aren't lost while we wait
        # for psutil to report it.
        self.unknown: deque = deque(maxlen=UNKNOWN_BUFFER_MAX)

    def _log(self, **event) -> None:
        self.index.write(json.dumps(event) + "\n")

    def on_packet(self, pkt) -> None:
        parsed = parse_packet(pkt)
        if parsed is None:
            return
        with self.lock:
            key, direction = self._match(parsed)
            if key is None:
                self.unknown.append(parsed)
                return
            self._handle(self.conns[key], direction, parsed)

    def _match(self, p) -> tuple[ConnKey | None, str]:
        src, sport, dst, dport = p["src"], p["sport"], p["dst"], p["dport"]
        out = ConnKey(src, sport, dst, dport)
        if out in self.conns:
            return out, "c2s"
        back = ConnKey(dst, dport, src, sport)
        if back in self.conns:
            return back, "s2c"
        return None, ""

    def _handle(self, rec: ConnRecorder, direction: str, p) -> None:
        if self.pcap is not None:
            self.pcap.write(p["pkt"])
        d = rec.dirs[direction]
        events = d.stream.feed(p["seq"], p["payload"], syn=p["syn"])
        self._write_events(rec, direction, d, events, p["t"])
        if p["fin"] or p["rst"]:
            self._write_events(rec, direction, d, d.stream.flush(), p["t"])
            self._log(t=p["t"], conn=rec.folder.name, dir=direction, event="rst" if p["rst"] else "fin")

    def _write_events(self, rec, direction, d: Direction, events, t: float) -> None:
        for ev in events:
            if isinstance(ev, Data):
                d.file.write(ev.payload)
                d.bytes += len(ev.payload)
                if len(d.sample) < SAMPLE_BYTES:
                    d.sample += ev.payload[: SAMPLE_BYTES - len(d.sample)]
                self._log(t=t, conn=rec.folder.name, dir=direction, event="data", off=ev.offset, len=len(ev.payload))
            elif isinstance(ev, Gap):
                # Keep file offsets equal to stream offsets: fill holes with zeros.
                d.file.write(b"\x00" * ev.size)
                d.gaps += 1
                self._log(t=t, conn=rec.folder.name, dir=direction, event="gap", off=ev.offset, len=ev.size)

    def add_connections(self, keys: set[ConnKey]) -> list[ConnKey]:
        added = []
        with self.lock:
            for key in keys - self.conns.keys():
                folder = self.out_dir / f"conn{len(self.conns) + 1:02d}_{key.label()}"
                rec = ConnRecorder(key, folder)
                self.conns[key] = rec
                self._log(t=time.time(), conn=folder.name, event="open", local=f"{key.local_ip}:{key.local_port}",
                          remote=f"{key.remote_ip}:{key.remote_port}")
                added.append(key)
            if added:
                self._replay_unknown()
        return added

    def _replay_unknown(self) -> None:
        cutoff = time.time() - UNKNOWN_BUFFER_SECONDS
        keep = deque(maxlen=UNKNOWN_BUFFER_MAX)
        for p in self.unknown:
            key, direction = self._match(p)
            if key is not None:
                self._handle(self.conns[key], direction, p)
            elif p["t"] >= cutoff:
                keep.append(p)
        self.unknown = keep

    def close(self) -> None:
        with self.lock:
            for rec in self.conns.values():
                for name, d in rec.dirs.items():
                    self._write_events(rec, name, d, d.stream.flush(), time.time())
                    d.close()
            self.index.close()
            if self.pcap is not None:
                self.pcap.close()

    def summary(self) -> str:
        lines = []
        for rec in self.conns.values():
            k = rec.key
            lines.append(f"{rec.folder.name}  {k.remote_ip}:{k.remote_port}")
            for name, d in rec.dirs.items():
                s = bytes(d.sample)
                hint = ""
                if s[:1] in (b"\x16", b"\x17") and s[1:2] == b"\x03":
                    hint = "  [TLS - büyük ihtimalle oyun protokolü değil]"
                ent = shannon_entropy(s)
                lines.append(f"    {name}: {d.bytes:>10,} bayt  boşluk={d.gaps}  entropi={ent:.2f} bit/bayt{hint}")
                if s:
                    lines.append(f"         ilk baytlar: {s[:32].hex(' ')}")
        if not lines:
            return "Hiç oyun bağlantısı kaydedilmedi."
        lines.append("")
        lines.append("Entropi ~7.9+ ise veri şifreli ya da sıkıştırılmış; ~4-7 arası düz ikili protokol olabilir.")
        return "\n".join(lines)


def parse_packet(pkt):
    if TCP not in pkt:
        return None
    if IP in pkt:
        ip = pkt[IP]
    elif IPv6 in pkt:
        ip = pkt[IPv6]
    else:
        return None
    tcp = pkt[TCP]
    flags = int(tcp.flags)
    return {
        "pkt": pkt,
        "t": float(pkt.time),
        "src": ip.src, "dst": ip.dst, "sport": tcp.sport, "dport": tcp.dport,
        "seq": tcp.seq,
        # Raw only: tcp.payload would include Ethernet padding on short frames.
        "payload": tcp[Raw].load if Raw in tcp else b"",
        "fin": bool(flags & 0x01), "syn": bool(flags & 0x02), "rst": bool(flags & 0x04),
    }


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except AttributeError:
        return True  # non-Windows; let the sniffer fail on its own if needed


def _route_iface(ip: str):
    try:
        return conf.route.route(ip)[0]
    except Exception:
        return None


def _start_sniffer(session: Session, ifaces: list) -> AsyncSniffer:
    sniffer = AsyncSniffer(iface=ifaces if len(ifaces) > 1 else ifaces[0], filter="tcp",
                           prn=session.on_packet, store=False)
    sniffer.start()
    return sniffer


def list_candidates(pattern: str) -> None:
    pids = find_game_pids(pattern)
    if not pids:
        print(f"'{pattern}' ile eşleşen süreç yok. Oyun açık mı? --process ile farklı bir ad dene.")
        return
    for pid, name in pids.items():
        print(f"PID {pid}  {name}")
        for c in sorted(game_connections({pid}), key=lambda c: c.remote_port):
            print(f"    {c.local_ip}:{c.local_port} -> {c.remote_ip}:{c.remote_port}  (arayüz: {_route_iface(c.remote_ip)})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aion 2 TCP trafiğini pasif olarak kaydeder.")
    ap.add_argument("--process", default=DEFAULT_PROCESS_PATTERN, help="süreç adı regex'i (varsayılan: aion)")
    ap.add_argument("--pid", type=int, action="append", help="belirli PID (birden çok verilebilir)")
    ap.add_argument("--iface", help="Npcap arayüz adı (varsayılan: oyun sunucusuna giden rota)")
    ap.add_argument("--exclude-port", type=int, action="append", default=[], help="atlanacak uzak port (ör. 443)")
    ap.add_argument("--out", default="captures", help="çıktı klasörü")
    ap.add_argument("--duration", type=float, help="saniye cinsinden süre (varsayılan: Ctrl+C'ye kadar)")
    ap.add_argument("--no-pcap", action="store_true", help="raw.pcap yazma")
    ap.add_argument("--stop-file", help="bu dosya oluşunca kaydı düzgünce bitir (arka planda çalıştırırken)")
    ap.add_argument("--list", action="store_true", help="eşleşen süreçleri ve bağlantılarını listele ve çık")
    args = ap.parse_args(argv)

    if args.list:
        list_candidates(args.process)
        return 0
    if not _is_admin():
        # Npcap installed without "admin only" mode works unelevated.
        print("Uyarı: Yönetici değil. Npcap 'yalnızca yönetici' modundaysa yakalama başarısız olur.", file=sys.stderr)

    out_dir = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    session = Session(out_dir, write_pcap=not args.no_pcap)
    exclude = set(args.exclude_port)
    if args.iface:
        ifaces = [args.iface]
    else:
        # Default adapter plus loopback (local proxies like ExitLag).
        ifaces = [str(conf.iface)]
        loop = _route_iface("127.0.0.1")
        if loop is not None and str(loop) not in ifaces:
            ifaces.append(str(loop))
    sniffer = _start_sniffer(session, ifaces)
    print(f"Kayıt: {out_dir}  (arayüzler: {', '.join(ifaces)})  — durdurmak için Ctrl+C")

    deadline = time.time() + args.duration if args.duration else None
    stop_file = Path(args.stop_file) if args.stop_file else None
    waiting_shown = False
    try:
        while deadline is None or time.time() < deadline:
            if stop_file is not None and stop_file.exists():
                stop_file.unlink()
                break
            pids = set(args.pid) if args.pid else set(find_game_pids(args.process))
            if not pids and not waiting_shown:
                print("Oyun süreci bekleniyor...")
                waiting_shown = True
            for key in session.add_connections(game_connections(pids, exclude)):
                print(f"+ bağlantı {key.local_port} -> {key.remote_ip}:{key.remote_port}")
                route = _route_iface(key.remote_ip)
                if not args.iface and route is not None and str(route) not in ifaces:
                    # Game traffic goes through another adapter (e.g. VPN): listen there too.
                    print(f"  oyun trafiği '{route}' arayüzünde, dinleyiciye ekleniyor")
                    sniffer.stop()
                    ifaces.append(str(route))
                    sniffer = _start_sniffer(session, ifaces)
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        sniffer.stop()
        session.close()

    print()
    print(session.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
