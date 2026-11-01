"""Opcode report for a capture: when each server opcode appeared, how often, how big.

    python -m aion2market.report captures/<run> [--opcode 0x3600 ...] [--after HH:MM:SS]
"""

from __future__ import annotations

import argparse
import bisect
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .protocol import Frame, parse_stream


def _chunk_times(run: Path, conn: str) -> tuple[list[int], list[float]]:
    """End offsets and arrival times of s2c chunks for one connection."""
    ends, times = [], []
    for line in (run / "index.jsonl").read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e.get("conn") == conn and e.get("dir") == "s2c" and e["event"] == "data":
            ends.append(e["off"] + e["len"])
            times.append(e["t"])
    return ends, times


def load_frames(run: Path) -> list[tuple[float, str, Frame]]:
    out = []
    for conn_dir in sorted(p for p in run.iterdir() if p.is_dir()):
        data = (conn_dir / "s2c.bin").read_bytes()
        frames, used = parse_stream(data)
        if not frames or used < len(data) * 0.9:
            continue  # not the game protocol (or unparseable)
        ends, times = _chunk_times(run, conn_dir.name)
        for f in frames:
            k = min(bisect.bisect_right(ends, f.offset), len(times) - 1)
            out.append((times[k], conn_dir.name, f))
    out.sort(key=lambda x: x[0])
    return out


def strings(b: bytes, min_len: int = 4) -> list[str]:
    ascii_ = [m.decode() for m in re.findall(rb"[\x20-\x7e]{%d,}" % min_len, b)]
    utf16 = [m.decode("utf-16le") for m in re.findall(rb"(?:[\x20-\x7e]\x00|[\x00-\xff][\xac-\xd7]){%d,}" % min_len, b)]
    return ascii_ + utf16


def value_patterns(n: int) -> dict[str, bytes]:
    """Byte encodings a number might use on the wire."""
    v, out = n, bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            break
    pats = {"varint": bytes(out), "u64": n.to_bytes(8, "little")}
    if n < 1 << 32:
        pats["u32"] = n.to_bytes(4, "little")
    return pats


def _clock(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%H:%M:%S")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--opcode", action="append", default=[], help="bu opcode'ların örneklerini dök (ör. 0x3600)")
    ap.add_argument("--after", help="sadece bu saatten sonrası (HH:MM:SS)")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--find", type=int, action="append", default=[], help="bu sayıyı çerçevelerde ara (u32/u64/varint)")
    args = ap.parse_args(argv)

    frames = load_frames(args.run)
    if args.after:
        day = datetime.fromtimestamp(frames[0][0]).date()
        cutoff = datetime.combine(day, datetime.strptime(args.after, "%H:%M:%S").time()).timestamp()
        frames = [x for x in frames if x[0] >= cutoff]

    if args.find:
        for n in args.find:
            for name, pat in value_patterns(n).items():
                for t, _conn, f in frames:
                    i = f.payload.find(pat)
                    while i != -1:
                        ctx = f.payload[max(0, i - 24):i + len(pat) + 24]
                        print(f"{n} as {name:6} {_clock(t)} op=0x{f.opcode:04x} len={len(f.payload)} @{i}: {ctx.hex(' ')}")
                        i = f.payload.find(pat, i + 1)
        return 0

    if args.opcode:
        wanted = {int(o, 16) for o in args.opcode}
        shown: defaultdict[int, int] = defaultdict(int)
        for t, conn, f in frames:
            if f.opcode in wanted and shown[f.opcode] < args.samples:
                shown[f.opcode] += 1
                print(f"{_clock(t)} {conn} op=0x{f.opcode:04x} len={len(f.payload)} lz4={f.compressed}")
                print("   ", f.payload[:256].hex(" "))
                s = strings(f.payload)
                if s:
                    print("    strings:", s[:20])
        return 0

    by_op = defaultdict(list)
    for t, _, f in frames:
        by_op[f.opcode].append((t, len(f.payload)))
    print(f"{len(frames)} çerçeve, {len(by_op)} opcode, {_clock(frames[0][0])} - {_clock(frames[-1][0])}")
    print(f"{'opcode':>8} {'adet':>6} {'toplam':>8} {'max':>6}  ilk      son")
    for op, items in sorted(by_op.items(), key=lambda kv: -sum(s for _, s in kv[1])):
        sizes = [s for _, s in items]
        print(f"  0x{op:04x} {len(items):>6} {sum(sizes):>8} {max(sizes):>6}  {_clock(items[0][0])} {_clock(items[-1][0])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
