import lz4.block

from aion2market.protocol import COMPRESSED, Frame, parse_stream


def varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def frame(opcode: int, payload: bytes) -> bytes:
    body = opcode.to_bytes(2, "little") + payload
    return varint(len(body) + 4) + body


def test_observed_small_frame():
    # Real bytes from a capture: L=0x0e, 11 bytes total.
    raw = bytes.fromhex("0e 00 36 f2 82 54 85 a1 01 00 00")
    frames, used = parse_stream(raw)
    assert used == 11
    assert frames == [Frame(0, 0x3600, bytes.fromhex("f2 82 54 85 a1 01 00 00"))]


def test_two_byte_varint_length():
    payload = bytes(range(256)) * 2
    data = frame(0x3611, payload)
    assert data[0] & 0x80  # needs 2-byte varint
    tail = frame(0x371D, b"x")
    frames, used = parse_stream(data + tail)
    assert used == len(data) + len(tail)
    assert [f.opcode for f in frames] == [0x3611, 0x371D]
    assert frames[0].payload == payload


def test_compressed_batch_is_expanded():
    inner = frame(0x382A, b"hello" * 20) + frame(0x3600, b"\x01\x02")
    comp = lz4.block.compress(inner, store_size=False)
    batch = frame(COMPRESSED, len(inner).to_bytes(4, "little") + comp)
    frames, used = parse_stream(frame(0x3600, b"a") + batch)
    assert used == len(frame(0x3600, b"a")) + len(batch)
    assert [(f.opcode, f.compressed) for f in frames] == [(0x3600, False), (0x382A, True), (0x3600, True)]
    assert frames[1].payload == b"hello" * 20
    assert frames[1].offset == frames[2].offset == len(frame(0x3600, b"a"))


def test_truncated_tail_reports_resume_offset():
    data = frame(0x3600, b"abc")
    frames, used = parse_stream(data + frame(0x3600, b"defgh")[:-2])
    assert len(frames) == 1 and used == len(data)
