"""Aion 2 server->client framing (observed through ExitLag, Oct 2026).

    frame  = varint L, then L - 4 bytes of body
    body   = u16le opcode, payload
    opcode 0xFFFF = compressed batch: u32le raw size, LZ4 block -> more frames

Client->server traffic is encrypted after the first (key exchange) frame,
so only the s2c direction is parsed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import lz4.block

COMPRESSED = 0xFFFF
LENGTH_BIAS = 4


@dataclass(frozen=True)
class Frame:
    offset: int        # offset in the outer stream (inner frames share their batch's offset)
    opcode: int
    payload: bytes
    compressed: bool = False


class FrameError(ValueError):
    pass


def read_varint(b: bytes, i: int) -> tuple[int, int]:
    v = shift = 0
    while i < len(b):
        x = b[i]
        i += 1
        v |= (x & 0x7F) << shift
        if not x & 0x80:
            return v, i
        shift += 7
        if shift > 28:
            break
    raise FrameError("bad varint")


def split_frames(b: bytes, base: int = 0, compressed: bool = False) -> Iterator[Frame | int]:
    """Yield frames from b; yields an int (resume offset) if the data is incomplete or corrupt."""
    i = 0
    while i < len(b):
        try:
            length, j = read_varint(b, i)
        except FrameError:
            yield i
            return
        end = j + length - LENGTH_BIAS
        if length < LENGTH_BIAS + 2 or end > len(b):
            yield i
            return
        opcode = int.from_bytes(b[j:j + 2], "little")
        payload = b[j + 2:end]
        off = base if compressed else base + i
        if opcode == COMPRESSED:
            raw = int.from_bytes(payload[:4], "little")
            try:
                inner = lz4.block.decompress(payload[4:], uncompressed_size=raw)
            except lz4.block.LZ4BlockError as e:
                raise FrameError(f"lz4 failed at {off}") from e
            for f in split_frames(inner, off, compressed=True):
                if isinstance(f, int):
                    raise FrameError(f"truncated frame inside batch at {off}")
                yield f
        else:
            yield Frame(off, opcode, payload, compressed)
        i = end


def parse_stream(b: bytes) -> tuple[list[Frame], int]:
    """Parse a whole s2c stream; return (frames, bytes consumed)."""
    frames = []
    for f in split_frames(b):
        if isinstance(f, int):
            return frames, f
        frames.append(f)
    return frames, len(b)
